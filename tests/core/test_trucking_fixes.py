"""Regression tests for the trucking fixes, built on real round mails and trucker replies."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from core.agents.directory import load_directory
from core.agents.trucker import (
    EmailTruckerPickupSource,
    best_offer,
    parse_hours,
    parse_price,
    request_body,
)
from core.contracts import RFQ, Mail, PickupPrice, Preference
from mail import extract as extract_module
from mail import kit
from mail.config import settings as mail_settings

FIXTURES = Path(__file__).parent / "fixtures"
KIT = FIXTURES / "kit"
DIRECTORY = load_directory(KIT)
NOW = datetime(2026, 11, 21, 16, 26, tzinfo=UTC)


@pytest.fixture(autouse=True)
def kit_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kit, "settings", mail_settings.__class__(kit_dir=KIT))


def real(name: str) -> dict:
    return json.loads((FIXTURES / "mail" / name).read_text(encoding="utf-8"))


def run(raw: dict):
    return extract_module.extract(raw["subject"], raw["body"], raw["from"], str(raw["id"]))


def rfq(zone: str = "93", postcode: str | None = None, kg: str = "572") -> RFQ:
    return RFQ(
        mail_id=3638,
        thread_root_id=3638,
        customer="auer-maschinenbau@hackloop.mail",
        subject="Air freight quote",
        origin="MUC",
        destination="SGN",
        pieces=(),
        gross_kg=Decimal(kg),
        volume_cbm=Decimal("2.29"),
        door_pickup=True,
        pickup_zone=zone,
        pickup_postcode=postcode,
        preference=Preference.CHEAPEST,
        preference_assumed=False,
        received_at=NOW,
        notes=("pieces: 11",),
    )


def reply(sender: str, body: str, subject: str = "Re: Pickup request 3638 zone 93 to MUC") -> Mail:
    return Mail(id=99, sender=sender, to="wrathofcode@hackloop.mail", subject=subject, body=body,
                in_reply_to=None, references=(), received_at=NOW)


# T1: round 15 had an old forwarded mail "AMSTERDAM SCHIPHOL - HKG / 128 PCS 165 KGS" in the
# subject; its 128 pieces were added to the real 11 (trucker request said "Pieces: 139").
def test_forwarded_subject_does_not_add_pieces() -> None:
    x = run(real("real_rfq_3638.json"))
    assert x.pieces == 11
    assert x.shipment is not None and x.shipment.destination == "SGN"


# T11: round 16 says "pickup from our warehouse", no postcode, signed only "Mira Petersen /
# Nordlicht Audio". With an empty memory the request could not be read and was held.
def test_no_postcode_and_no_memory_is_still_quoted() -> None:
    x = run(real("real_rfq_3941.json"))
    assert x.shipment is not None, x.missing
    assert x.shipment.door_pickup and x.shipment.pickup_zone == extract_module.DEFAULT_PICKUP_ZONE
    assert any("pickup address unknown" in p for p in x.problems)


def test_memory_learned_from_mailbox_gives_the_real_site() -> None:
    earlier = real("real_rfq_1978.json")  # same customer, round 9: "our site in 36627 (Fulda)"
    assert extract_module.learn_pickups([earlier]) == 1
    x = run(real("real_rfq_3941.json"))
    assert x.shipment is not None
    assert (x.shipment.pickup_zone, x.shipment.origin) == ("36", "FRA")


# T2: a request without a 5-digit postcode gets "We do not serve this lane/zone: postcode 93".
def test_request_always_has_a_five_digit_postcode() -> None:
    body = request_body(rfq(), "93", "Regensburg", "MUC")
    assert "Pickup postcode: 93047." in body
    assert "Pieces: 11." in body
    kept = request_body(rfq(postcode="93055"), "93", "Regensburg", "MUC")
    assert "Pickup postcode: 93055." in kept


# T3 / T4: answer "do not serve" and "to quote we need" once, and wait for the real price.
@pytest.mark.parametrize(
    "refusal",
    [
        "Hello,\n\nthank you for your request. We do not serve this lane/zone: pickup postcode 93.\n"
        "We collect in postcode zones 60, 70, 80, 84, 93 (first two digits).",
        "Hello,\n\nthank you for your request. To quote we need:\n- the volume in cbm (or the "
        "dimensions and number of pieces)",
    ],
)
def test_refusal_gets_one_follow_up_and_we_keep_waiting(refusal: str) -> None:
    async def scenario() -> tuple[list, bool, object, bool, int]:
        sender = Fake()
        source = EmailTruckerPickupSource(DIRECTORY, sender, lambda: NOW)
        await source.request(rfq())
        asked = sorted({to for to, _, _ in sender.sent})
        first = len(sender.sent)
        for to in asked:
            source.offer(reply(to, refusal))
        await asyncio.sleep(0)
        waiting = not source.all_answered(3638)
        late = rfq().model_copy(update={"received_at": NOW - timedelta(seconds=300)})
        pick = await source.collect(late)
        follow_ups = sender.sent[first:]
        for to in asked:  # a second refusal after our follow-up is final: no third mail
            source.offer(reply(to, refusal))
        await asyncio.sleep(0)
        return follow_ups, waiting, pick, source.all_answered(3638), len(sender.sent) - first

    follow_ups, waiting, pick, final, total_follow_ups = asyncio.run(scenario())
    assert follow_ups and all("93047" in body for _, _, body in follow_ups)
    assert len(follow_ups) == len({to for to, _, _ in follow_ups})
    assert waiting and pick is None
    assert final and total_follow_ups == len(follow_ups)


class Fake:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send_new(self, to: str, subject: str, body: str) -> int:
        self.sent.append((to, subject, body))
        return 5000 + len(self.sent)


# T5: an offer that does not state its pickup time must not be dropped.
def test_offer_without_pickup_time_is_kept() -> None:
    def price(total: str, hours: str | None) -> PickupPrice:
        return PickupPrice(source="t", trucker=total, zone="51", total=Decimal(total), currency="EUR",
                           received_at=NOW, pickup_hours=None if hours is None else Decimal(hours))

    assert best_offer([price("128.18", None), price("208.88", "11")]).total == Decimal("128.18")


# T7: reply formats truckers may use next.
@pytest.mark.parametrize(
    ("body", "amount", "currency"),
    [
        ("Base rate 100.00 EUR plus fuel surcharge 20.00 EUR, all-in 120.00 EUR. Pickup time: 10 hours.", "120.00", "EUR"),
        ("Truck 80.00 EUR, tail-lift 15.00 EUR. Total all-in price: 95.00 EUR.", "95.00", "EUR"),
        ("Our price is 95,- EUR all-in. Pickup within 24 hours.", "95", "EUR"),
        ("Unser Preis für die Abholung: 1.234,50 EUR. Abholzeit: 6 Stunden.", "1234.50", "EUR"),
        # real round-15 reply stays unchanged
        ("Our all-in price for pickup in Regensburg and delivery to Munich Airport is 90.60 EUR.", "90.60", "EUR"),
        ("Price: 100.00 EUR excl. 19% VAT (119.00 EUR incl. VAT). Pickup time: 8 hours.", "100.00", "EUR"),
    ],
)
def test_price_formats(body: str, amount: str, currency: str) -> None:
    assert parse_price(body) == (Decimal(amount), currency)


@pytest.mark.parametrize(
    ("body", "hours"),
    [
        ("Abholzeit: 6 Stunden", "6"),
        ("Abholung in 1 Tag", "24"),
        ("We can collect tomorrow (next-day pickup).", "24"),
        ("All-in price 99.00 EUR, pickup in 18h.", "18"),
        ("Pickup within 30 hours of cargo readiness.", "30"),
        ("Pickup lead time is 11 hours", "11"),
        ("Pickup time: 2 days.", "48"),
    ],
)
def test_pickup_time_formats(body: str, hours: str) -> None:
    assert parse_hours(body) == Decimal(hours)


# T6: the estimate scales by weight per trucker instead of the lowest price ever seen.
def test_estimate_scales_with_weight(tmp_path: Path) -> None:
    history = tmp_path / "pickup_history.jsonl"
    rows = [
        {"zone": "93", "airport": "MUC", "trucker": "Elbkante Logistik", "total": "90.60",
         "currency": "EUR", "kg": "572", "hours": "20"},
        {"zone": "93", "airport": "MUC", "trucker": "Elbkante Logistik", "total": "300.00",
         "currency": "EUR", "kg": "2000", "hours": "20"},
    ]
    history.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    source = EmailTruckerPickupSource(DIRECTORY, Fake(), lambda: NOW, history_path=history)
    guess = source.estimate(rfq(kg="1144"))
    # nearest weight is 572 kg: 90.60 * sqrt(1144 / 572) = 128.13
    assert guess is not None and guess.total == Decimal("128.13")
