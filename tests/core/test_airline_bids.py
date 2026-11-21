from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from test_orchestrator import KIT, NOW, FakeExtractor, harness, mail

from core.agents.airline_bids import (
    AirlineBidSource,
    best_by_score,
    bid_score,
    parse_airline_reply,
)
from core.agents.directory import load_directory
from core.contracts import (
    RFQ,
    LlmUsage,
    Mail,
    PortalDown,
    Preference,
    PriceOption,
    SourceUnavailable,
)

REPLY = (
    "Our all-in air freight rate from FRA to ASU is 2264.60 EUR, including freight and all "
    "surcharges.\n\nTransit time: 3 days\nOffer valid until: 2026-11-28"
)
NOT_SERVED = "We do not serve this lane/zone: FRA-ASU. We fly CGN-KTM instead."
DIRECTORY = load_directory(KIT)


@dataclass(frozen=True)
class Lane:
    origin: str
    destination: str


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send_new(self, to: str, subject: str, body: str) -> int | None:
        self.sent.append((to, subject, body))
        return 500 + len(self.sent)


def ports(*lanes: tuple[str, str]):
    async def load() -> list[Lane]:
        return [Lane(o, d) for o, d in lanes]

    return load


def rfq(destination: str = "ASU", preference: Preference = Preference.CHEAPEST) -> RFQ:
    return RFQ(
        mail_id=7,
        thread_root_id=7,
        customer="buyer@customer.example",
        subject="Quote",
        origin="FRA",
        destination=destination,
        pieces=(),
        gross_kg=Decimal("100"),
        door_pickup=False,
        pickup_zone=None,
        preference=preference,
        preference_assumed=False,
        received_at=NOW,
    )


def reply(mail_id: int, sender: str, subject: str, body: str) -> Mail:
    return mail(mail_id, sender=sender, subject=subject, body=body)


def option(carrier: str, total: str, days: int) -> PriceOption:
    return PriceOption(
        source="bid", carrier=carrier, total=Decimal(total), currency="EUR", transit_days=days
    )


def test_parse_priced_reply() -> None:
    parsed = parse_airline_reply(REPLY)
    assert parsed is not None
    assert (parsed.total, parsed.currency, parsed.transit_days) == (Decimal("2264.60"), "EUR", 3)


def test_do_not_serve_reply_is_ignored() -> None:
    assert parse_airline_reply(NOT_SERVED) is None


async def test_bids_requested_only_when_portal_has_no_lane() -> None:
    sender = FakeSender()
    source = AirlineBidSource(DIRECTORY, sender, ports(("FRA", "ORD"), ("FRA", "ASU")))
    assert await source.request(rfq("ASU")) is False
    assert sender.sent == []

    source = AirlineBidSource(DIRECTORY, sender, ports(("FRA", "ORD")))
    assert await source.request(rfq("ASU")) is True
    assert sorted(to for to, _, _ in sender.sent) == sorted(
        c.email for c in DIRECTORY.airlines_serving("ASU")
    )
    assert all(subject.startswith("[BID 7-") for _, subject, _ in sender.sent)
    await source.request(rfq("ASU"))
    assert len(sender.sent) == 4


async def test_ports_failure_sends_no_bids() -> None:
    async def broken() -> list[Lane]:
        raise RuntimeError("down")

    sender = FakeSender()
    source = AirlineBidSource(DIRECTORY, sender, broken)
    assert await source.request(rfq("ASU")) is False
    assert sender.sent == []


async def test_reply_becomes_bid_option_and_unknown_or_declined_are_ignored() -> None:
    sender = FakeSender()
    source = AirlineBidSource(DIRECTORY, sender, ports())
    await source.request(rfq("ASU"))
    to, subject, _ = sender.sent[0]
    other_to, other_subject, _ = sender.sent[1]
    assert source.offer(reply(900, "stranger@x.example", f"Re: {subject}", REPLY)) is None
    assert source.offer(reply(901, other_to, f"Re: {other_subject}", NOT_SERVED)) is None
    stored = source.offer(reply(902, to, f"Re: {subject}", REPLY))
    assert stored is not None
    assert stored.source == "bid"
    assert stored.carrier == DIRECTORY.by_email(to).name
    assert (stored.total, stored.currency, stored.transit_days) == (Decimal("2264.60"), "EUR", 3)
    assert source.options(7) == [stored]
    assert source.waiting(7)


def test_bid_score_and_best_by_score() -> None:
    cheap, fast, middle = option("A", "1000", 10), option("B", "2000", 2), option("C", "1200", 3)
    assert bid_score(cheap, Decimal("1000"), 2) == Decimal("3.0")
    assert bid_score(middle, Decimal("1000"), 2) == Decimal("1.35")
    assert best_by_score([cheap, fast, middle]) is middle


class LaneExtractor(FakeExtractor):
    def __init__(self, destination: str, preference: Preference = Preference.CHEAPEST) -> None:
        super().__init__()
        self.destination = destination
        self.preference = preference

    async def extract(self, source: Mail) -> tuple[RFQ, LlmUsage | None]:
        base, usage = await super().extract(source)
        return base.model_copy(
            update={"destination": self.destination, "preference": self.preference}
        ), usage


class NoLanePortal:
    name = "portal"

    async def quote(self, rfq: RFQ) -> list[PriceOption]:
        raise SourceUnavailable("portal has no lane")


class DownPortal:
    name = "portal"

    async def quote(self, rfq: RFQ) -> list[PriceOption]:
        raise PortalDown("portal ports failed: PortalUnavailable: ask ratedesk@hackloop.mail")


def bid_harness(tmp_path: Path, portal, lanes, preference=Preference.CHEAPEST):
    h = harness(tmp_path)
    clock = {"now": NOW + timedelta(seconds=5)}
    sender = FakeSender()
    h.orchestrator.clock = lambda: clock["now"]
    h.orchestrator.sources = [portal]
    h.orchestrator.extractor = LaneExtractor("ASU", preference)
    h.orchestrator.bids = AirlineBidSource(DIRECTORY, sender, ports(*lanes))
    return h, sender, clock


async def wait_for(condition, limit_s: float = 2.0) -> None:
    for _ in range(int(limit_s / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met")


async def test_email_only_lane_waits_for_bids_then_quotes_by_preference(tmp_path: Path) -> None:
    h, sender, clock = bid_harness(tmp_path, NoLanePortal(), [("FRA", "ORD")], Preference.FASTEST)
    h.mailbox.batches = [[mail(1)]]
    await h.orchestrator.poll_once()
    await wait_for(lambda: len(sender.sent) == 4)
    replies = [
        "Our all-in air freight rate from FRA to ASU is 900.00 EUR, including all surcharges."
        "\n\nTransit time: 6 days",
        "Our all-in air freight rate from FRA to ASU is 1500.00 EUR, including all surcharges."
        "\n\nTransit time: 2 days",
    ]
    for index, body in enumerate(replies):
        to, subject, _ = sender.sent[index]
        h.mailbox.batches.append([reply(20 + index, to, f"Re: {subject}", body)])
        await h.orchestrator.poll_once()
    await asyncio.sleep(0.05)
    assert h.orchestrator.outbox.empty(), "two of four airlines still pending: keep waiting"
    clock["now"] = NOW + timedelta(seconds=h.orchestrator.policy.wait_until_s + 1)
    await wait_for(lambda: not h.orchestrator.outbox.empty())
    quote = h.orchestrator.outbox.get_nowait()
    assert quote.option.source == "bid"
    assert quote.option.transit_days == 2
    assert quote.total == Decimal("1500.00")


async def test_all_bids_answered_quotes_cheapest_without_waiting(tmp_path: Path) -> None:
    h, sender, _ = bid_harness(tmp_path, NoLanePortal(), [])
    h.mailbox.batches = [[mail(1)]]
    await h.orchestrator.poll_once()
    await wait_for(lambda: len(sender.sent) == 4)
    for index, (to, subject, _) in enumerate(sender.sent):
        body = NOT_SERVED if index else REPLY
        h.mailbox.batches.append([reply(30 + index, to, f"Re: {subject}", body)])
        await h.orchestrator.poll_once()
    await wait_for(lambda: not h.orchestrator.outbox.empty())
    assert h.orchestrator.outbox.get_nowait().total == Decimal("2264.60")


async def test_portal_lane_never_emails_airlines(tmp_path: Path) -> None:
    h, sender, _ = bid_harness(tmp_path, NoLanePortal(), [("FRA", "ASU")])
    h.orchestrator.clock = lambda: NOW + timedelta(seconds=320)
    h.mailbox.batches = [[mail(1, received_at=NOW)]]
    await h.orchestrator.poll_once()
    while h.orchestrator.tasks:
        await asyncio.gather(*list(h.orchestrator.tasks))
    assert sender.sent == []


async def test_portal_503_asks_rate_desk_once_and_uses_reply(tmp_path: Path) -> None:
    h, sender, _ = bid_harness(tmp_path, DownPortal(), [("FRA", "ASU")])
    h.mailbox.batches = [[mail(1)]]
    await h.orchestrator.poll_once()
    await wait_for(lambda: len(sender.sent) == 1)
    to, subject, body = sender.sent[0]
    assert to == "ratedesk@hackloop.mail"
    assert subject == "[BID 1-RATEDESK] Rate request FRA-ASU"
    assert "FRA to ASU" in body
    same = rfq().model_copy(update={"mail_id": 1, "thread_root_id": 1})
    assert await h.orchestrator.bids.request_rate_desk(same) is False
    assert len(sender.sent) == 1
    h.mailbox.batches.append(
        [
            reply(
                40,
                "ratedesk@hackloop.mail",
                f"Re: {subject}",
                "Pampero Air Cargo can do FRA-ASU all-in 1800.00 EUR.\nTransit time: 4 days",
            )
        ]
    )
    await h.orchestrator.poll_once()
    await wait_for(lambda: not h.orchestrator.outbox.empty())
    quote = h.orchestrator.outbox.get_nowait()
    assert quote.option.carrier == "Pampero Air Cargo"
    assert quote.total == Decimal("1800.00")
