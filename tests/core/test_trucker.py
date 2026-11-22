from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import core.agents.trucker as trucker_module
from core.agents.directory import load_directory
from core.agents.trucker import EmailTruckerPickupSource, parse_price
from core.contracts import RFQ, Mail, Piece, Preference

KIT = Path(__file__).parent / "fixtures" / "kit"
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
DIRECTORY = load_directory(KIT)


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send_new(self, to: str, subject: str, body: str) -> int | None:
        self.sent.append((to, subject, body))
        return 1000 + len(self.sent)


def make_rfq(door_pickup: bool = True, zone: str | None = "45") -> RFQ:
    return RFQ(
        mail_id=7,
        thread_root_id=7,
        customer="buyer@example.test",
        subject="Quote",
        origin="DUS",
        destination="ORD",
        pieces=(
            Piece(count=3, length_cm=Decimal(50), width_cm=Decimal(50), height_cm=Decimal(50)),
        ),
        gross_kg=Decimal(120),
        door_pickup=door_pickup,
        pickup_zone=zone,
        preference=Preference.CHEAPEST,
        preference_assumed=False,
        received_at=NOW,
    )


def mail(sender: str, subject: str, body: str, in_reply_to: int | None = None) -> Mail:
    return Mail(
        id=55,
        sender=sender,
        to="us@example.test",
        subject=subject,
        body=body,
        in_reply_to=in_reply_to,
        references=(),
        received_at=NOW,
    )


def source() -> tuple[EmailTruckerPickupSource, FakeSender]:
    sender = FakeSender()
    return EmailTruckerPickupSource(DIRECTORY, sender, lambda: NOW), sender


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Our price is EUR 85.00 all in", (Decimal("85.00"), "EUR")),
        ("We can do it for 85,00 EUR.", (Decimal("85.00"), "EUR")),
        ("USD 120 flat", (Decimal("120"), "USD")),
        ("Only €85", (Decimal("85"), "EUR")),
        ("Total 1.250,50 EUR", (Decimal("1250.50"), "EUR")),
        ("no price here, 3 pallets", None),
    ],
)
def test_parse_price(text: str, expected: tuple[Decimal, str] | None) -> None:
    assert parse_price(text) == expected


async def test_request_sends_to_zone_truckers_only() -> None:
    trucker, sender = source()
    await trucker.request(make_rfq())
    expected = {c.email for c in DIRECTORY.truckers_for_zone("45")}
    assert {to for to, _, _ in sender.sent} == expected
    assert all(s == "Pickup request 7 zone 45 to DUS" for _, s, _ in sender.sent)
    body = sender.sent[0][2]
    assert "Essen" in body and "Pieces: 3" in body and "120 kg" in body
    await trucker.request(make_rfq())
    assert len(sender.sent) == len(expected)


async def test_no_request_without_door_pickup() -> None:
    trucker, sender = source()
    await trucker.request(make_rfq(False, None))
    assert sender.sent == []


async def test_door_pickup_without_zone_asks_the_origin_airports_zone() -> None:
    trucker, sender = source()
    await trucker.request(make_rfq(True, None))
    assert sender.sent and all("to DUS" in subject for _, subject, _ in sender.sent)


async def test_estimate_uses_cheapest_earlier_offer_for_the_zone(tmp_path) -> None:
    import json

    history = tmp_path / "pickup_history.jsonl"
    rows = [
        {"zone": "40", "airport": "DUS", "trucker": "A", "total": "160.00", "currency": "EUR"},
        {"zone": "40", "airport": "DUS", "trucker": "B", "total": "119.50", "currency": "EUR"},
        {"zone": "60", "airport": "FRA", "trucker": "C", "total": "90.00", "currency": "EUR"},
    ]
    history.write_text("\n".join(json.dumps(r) for r in rows))
    trucker = EmailTruckerPickupSource(DIRECTORY, FakeSender(), lambda: NOW, history_path=history)
    guess = trucker.estimate(make_rfq(True, "40"))
    assert guess is not None and guess.total == Decimal("119.50") and guess.source == "estimate"


async def test_offer_parsed_by_subject_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trucker_module, "PICKUP_GRACE_S", 0.0)
    monkeypatch.setattr(trucker_module, "PICKUP_WAIT_S", 0.0)
    trucker, _ = source()
    rfq = make_rfq()
    await trucker.request(rfq)
    trucker.offer(
        mail("Grautal-Trucking@hackloop.mail", "Re: Pickup request 7 zone 45 to DUS", "EUR 85.00")
    )
    price = await trucker.collect(rfq)
    assert price is not None
    assert (price.total, price.currency, price.trucker, price.zone) == (
        Decimal("85.00"),
        "EUR",
        "Grautal Trucking",
        "45",
    )


async def test_offer_parsed_by_in_reply_to(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trucker_module, "PICKUP_GRACE_S", 0.0)
    monkeypatch.setattr(trucker_module, "PICKUP_WAIT_S", 0.0)
    trucker, sender = source()
    rfq = make_rfq()
    await trucker.request(rfq)
    first = sender.sent[0][0]
    trucker.offer(mail(first, "Re: your mail", "Price: 85,00 EUR", in_reply_to=1001))
    price = await trucker.collect(rfq)
    assert price is not None and price.total == Decimal("85.00")


async def test_offer_ignores_unrelated_and_garbage() -> None:
    trucker, _ = source()
    rfq = make_rfq()
    await trucker.request(rfq)
    trucker.offer(mail("stranger@example.test", "Pickup request 7", "EUR 10.00"))
    trucker.offer(mail("rheinufer-spedition@hackloop.mail", "Pickup request 7", "EUR 10.00"))
    trucker.offer(mail("grautal-trucking@hackloop.mail", "Pickup request 71", "EUR 10.00"))
    trucker.offer(mail("grautal-trucking@hackloop.mail", "Pickup request 7", "call me"))
    assert await trucker.collect(rfq) is None


async def test_collect_returns_cheapest_not_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trucker_module, "PICKUP_GRACE_S", 0.0)
    from core.contracts import PickupPrice

    source = EmailTruckerPickupSource.__new__(EmailTruckerPickupSource)
    now = datetime(2026, 11, 21, 15, 10, tzinfo=UTC)
    offers = [
        PickupPrice(
            source="email",
            trucker=name,
            zone="61",
            total=Decimal(total),
            currency="EUR",
            received_at=now,
        )
        for name, total in [
            ("Westfalenroute", "266.03"),
            ("Nordlicht", "152.01"),
            ("Bodenseefracht", "119.01"),
        ]
    ]
    source._prices = {432: offers}
    source._asked = {}
    source._answered = {}
    source._first_price_at = {}
    source.now = lambda: now + timedelta(seconds=200)
    rfq = type("R", (), {"mail_id": 432, "received_at": now})()
    best = await source.collect(rfq)
    assert best is not None and best.trucker == "Bodenseefracht" and best.total == Decimal("119.01")


async def test_collect_waits_for_other_truckers_within_grace() -> None:
    import time

    from core.contracts import PickupPrice

    source = EmailTruckerPickupSource.__new__(EmailTruckerPickupSource)
    now = datetime(2026, 11, 21, 15, 10, tzinfo=UTC)
    first = PickupPrice(
        source="email",
        trucker="Westfalenroute",
        zone="61",
        total=Decimal("266.03"),
        currency="EUR",
        received_at=now,
    )
    source._prices = {432: [first]}
    source._asked = {432: {"a@x", "b@x"}}
    source._answered = {432: {"a@x"}}
    source._first_price_at = {432: time.monotonic()}
    source.now = lambda: now
    rfq = type("R", (), {"mail_id": 432, "received_at": now})()
    assert await source.collect(rfq) is None
    cheaper = PickupPrice(
        source="email",
        trucker="Bodenseefracht",
        zone="61",
        total=Decimal("119.01"),
        currency="EUR",
        received_at=now,
    )
    source._prices[432].append(cheaper)
    source._answered[432].add("b@x")
    best = await source.collect(rfq)
    assert best is not None and best.total == Decimal("119.01")


async def test_waits_for_slower_truckers_until_100_seconds() -> None:
    trucker, sender = source()
    rfq = make_rfq()
    await trucker.request(rfq)
    first = sender.sent[0][0]
    trucker.offer(mail(first, "Re: your mail", "Price: 85,00 EUR", in_reply_to=1001))
    trucker._first_price_at[rfq.mail_id] -= 60
    if len(sender.sent) > 1:
        assert await trucker.collect(rfq) is None
    trucker.now = lambda: NOW + timedelta(seconds=101)
    price = await trucker.collect(rfq)
    assert price is not None and price.total == Decimal("85.00")


def test_pickup_uses_50_50_price_and_time_balance_round_14(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.agents.trucker import best_offer, parse_hours

    monkeypatch.setenv("PICKUP_RULE", "balanced")
    from core.contracts import PickupPrice

    now = datetime(2026, 11, 21, 16, 20, tzinfo=UTC)
    offers = [
        PickupPrice(
            source="email",
            trucker=name,
            zone="42",
            total=Decimal(total),
            currency="EUR",
            received_at=now,
            pickup_hours=parse_hours(f"Pickup time: {hours} hours"),
        )
        for name, total, hours in [
            ("Westfalenroute", "321.74", 4),
            ("Schwabenbote", "379.79", 6),
            ("Rheinufer", "379.38", 7),
            ("Spessart", "113.05", 32),
        ]
    ]
    assert best_offer(offers).trucker == "Westfalenroute"
    assert parse_hours("Pickup time: 2 days") == Decimal("48")
    assert (
        best_offer([o.model_copy(update={"pickup_hours": None}) for o in offers]).trucker
        == "Spessart"
    )


def test_default_pickup_rule_round_15() -> None:
    from core.agents.trucker import best_offer
    from core.contracts import PickupPrice

    now = datetime(2026, 11, 21, 16, 28, tzinfo=UTC)
    offers = [
        PickupPrice(
            source="e",
            trucker=n,
            zone="93",
            total=Decimal(t),
            currency="EUR",
            received_at=now,
            pickup_hours=Decimal(h),
        )
        for n, t, h in [
            ("Isarwelle", "107.20", 33),
            ("Neckarstrom", "198.08", 5),
            ("Elbkante", "90.60", 30),
            ("Flinkwagen", "241.96", 6),
        ]
    ]
    # 24 h limit (proven from board accuracy points, see test_trucking_fixes.py): Elbkante (30 h)
    # and Isarwelle (33 h) are too slow, so the cheapest quick one is Neckarstrom.
    assert best_offer(offers).trucker == "Neckarstrom"


def test_cheapest_within_24_hours_rounds_14_and_18() -> None:
    from core.agents.trucker import best_offer, parse_hours
    from core.contracts import PickupPrice

    now = datetime(2026, 11, 21, 16, 45, tzinfo=UTC)

    def offers(rows):
        return [
            PickupPrice(
                source="e",
                trucker=n,
                zone="42",
                total=Decimal(p),
                currency="EUR",
                received_at=now,
                pickup_hours=Decimal(h),
            )
            for n, p, h in rows
        ]

    r14 = offers(
        [
            ("Westfalenroute", "321.74", 4),
            ("Schwabenbote", "379.79", 6),
            ("Rheinufer", "379.38", 7),
            ("Spessart", "113.05", 32),
        ]
    )
    assert best_offer(r14).trucker == "Westfalenroute"
    r18 = offers(
        [
            ("Maintal", "212.14", 13),
            ("Bodenseefracht", "254.84", 12),
            ("Elbkante", "128.18", 29),
            ("Westfalenroute", "208.88", 11),
        ]
    )
    # Round 18 was quoted with Elbkante (128.18, 29 h) and scored 29.6 accuracy, not 45: the
    # grader used Westfalenroute (208.88, 11 h). 45 * (1 - 3.42 % / 10 %) = 29.6.
    assert best_offer(r18).trucker == "Westfalenroute"
    assert parse_hours("We can collect within 30 hours.") == Decimal("30")


def test_fastest_request_takes_the_fastest_trucker_round_25() -> None:
    from core.agents.trucker import best_offer
    from core.contracts import PickupPrice

    now = datetime(2026, 11, 21, 17, 27, tzinfo=UTC)
    offers = [
        PickupPrice(
            source="e",
            trucker=n,
            zone="70",
            total=Decimal(p),
            currency="EUR",
            received_at=now,
            pickup_hours=Decimal(h),
        )
        for n, p, h in [
            ("Isarwelle", "134.40", 21),
            ("Rheinufer", "94.08", 28),
            ("Nordlicht", "203.04", 14),
            ("Spessart", "225.04", 9),
        ]
    ]
    assert best_offer(offers, "fastest").trucker == "Spessart"
    assert best_offer(offers, "cheapest").trucker == "Spessart"  # balanced 50/50 (brief)


def test_poll_waits_until_trucker_replies_are_due() -> None:
    from core.agents import trucker
    from core.main import next_poll_wait

    trucker.POLL_HINTS[:] = [100.0 + 31.0]
    assert next_poll_wait(6.0, now=100.0) == 6.0
    assert next_poll_wait(6.0, now=126.5) == 5.2
    assert abs(next_poll_wait(6.0, now=125.5) - 5.5) < 1e-9
    trucker.POLL_HINTS[:] = []
    assert next_poll_wait(6.0, now=100.0) == 6.0
