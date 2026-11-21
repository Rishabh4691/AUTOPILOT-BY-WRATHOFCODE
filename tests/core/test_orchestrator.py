from __future__ import annotations

import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from core.agents.classifier import RuleClassifier
from core.agents.directory import load_directory
from core.config import Settings, load_settings
from core.contracts import (
    RFQ,
    Event,
    LlmUsage,
    Mail,
    OutgoingMail,
    PickupPrice,
    Preference,
    PriceOption,
    Stage,
)
from core.orchestrator import Orchestrator
from core.store import Store

KIT = Path(__file__).parent / "fixtures" / "kit"
NOW = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)
CUSTOMER = "buyer@customer.example"


def make_settings(tmp_path: Path, kill_switch: bool = False) -> Settings:
    base = load_settings(tmp_path, {"FIVEU_API_KEY": "test-key", "DRY_RUN": "1"})
    return dataclasses.replace(base, kill_switch=kill_switch)


def mail(
    mail_id: int,
    sender: str = CUSTOMER,
    subject: str = "Quote request FRA to ORD",
    body: str = "Please quote FRA to ORD, 100 kg, cheapest.",
    references: tuple[int, ...] = (),
    in_reply_to: int | None = None,
    received_at: datetime = NOW,
) -> Mail:
    return Mail(
        id=mail_id,
        sender=sender,
        to="wrathofcode@hackloop.mail",
        subject=subject,
        body=body,
        in_reply_to=in_reply_to,
        references=references,
        received_at=received_at,
    )


class FakeMailbox:
    def __init__(self) -> None:
        self.batches: list[list[Mail]] = []
        self.sent: list[OutgoingMail] = []

    async def poll(self, since_id: int) -> tuple[list[Mail], int]:
        batch = self.batches.pop(0) if self.batches else []
        return batch, max([since_id, *[m.id for m in batch]])

    async def send(self, outgoing: OutgoingMail) -> Mail:
        self.sent.append(outgoing)
        return mail(10_000 + len(self.sent), sender="wrathofcode@hackloop.mail")

    async def read_one(self, message_id: int) -> Mail:
        raise NotImplementedError


class FakeExtractor:
    def __init__(self, door: bool = False) -> None:
        self.calls = 0
        self.door = door

    async def extract(self, source: Mail) -> tuple[RFQ, LlmUsage | None]:
        self.calls += 1
        return (
            RFQ(
                mail_id=source.id,
                thread_root_id=source.thread_root_id,
                customer=source.sender,
                subject=source.subject,
                origin="FRA",
                destination="ORD",
                pieces=(),
                gross_kg=Decimal("100"),
                door_pickup=self.door,
                pickup_zone="60" if self.door else None,
                preference=Preference.CHEAPEST,
                preference_assumed=False,
                received_at=source.received_at,
            ),
            None,
        )


class FakeSource:
    name = "portal"

    def __init__(self) -> None:
        self.calls = 0

    async def quote(self, rfq: RFQ) -> list[PriceOption]:
        self.calls += 1
        return [
            PriceOption(
                source="portal",
                carrier="Slow Air",
                total=Decimal("300"),
                currency="EUR",
                transit_days=5,
            ),
            PriceOption(
                source="portal",
                carrier="Cheap Air",
                total=Decimal("250.5"),
                currency="EUR",
                transit_days=6,
            ),
        ]


class FakePickup:
    name = "trucker_email"

    def __init__(self, price: PickupPrice | None) -> None:
        self.price = price
        self.requested = 0

    async def request(self, rfq: RFQ) -> None:
        self.requested += 1

    async def collect(self, rfq: RFQ) -> PickupPrice | None:
        return self.price


class FakeWriter:
    def __init__(self) -> None:
        self.calls = 0

    async def write(
        self, rfq: RFQ, option: PriceOption, total: Decimal, currency: str
    ) -> tuple[str, LlmUsage | None]:
        self.calls += 1
        return f"Our all-in price is {total} {currency}.", LlmUsage(
            model="fake", cost_usd=Decimal("0.0001")
        )


class ListSink:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)


@dataclasses.dataclass
class Harness:
    orchestrator: Orchestrator
    mailbox: FakeMailbox
    extractor: FakeExtractor
    writer: FakeWriter
    sink: ListSink
    store: Store


def harness(
    tmp_path: Path,
    settings: Settings | None = None,
    pickup: FakePickup | None = None,
    door: bool = False,
    now: datetime = NOW + timedelta(seconds=5),
) -> Harness:
    settings = settings or make_settings(tmp_path)
    store = Store(tmp_path / "app.db")
    mailbox = FakeMailbox()
    extractor = FakeExtractor(door=door)
    writer = FakeWriter()
    sink = ListSink()
    orchestrator = Orchestrator(
        settings=settings,
        store=store,
        mailbox=mailbox,
        classifier=RuleClassifier(settings, load_directory(KIT)),
        extractor=extractor,
        sources=[FakeSource()],
        pickup=pickup,
        writer=writer,
        events=sink,
        clock=lambda: now,
        tick_s=0.01,
    )
    return Harness(orchestrator, mailbox, extractor, writer, sink, store)


async def drain(h: Harness) -> None:
    while h.orchestrator.tasks:
        await asyncio.gather(*list(h.orchestrator.tasks))
    while not h.orchestrator.outbox.empty():
        await h.orchestrator.send_quote(h.orchestrator.outbox.get_nowait())


async def test_rfq_gets_one_reply_in_thread_with_cheapest_total(tmp_path: Path) -> None:
    h = harness(tmp_path)
    h.mailbox.batches = [[mail(1)]]
    await h.orchestrator.poll_once()
    await drain(h)
    assert len(h.mailbox.sent) == 1
    sent = h.mailbox.sent[0]
    assert sent.to == CUSTOMER
    assert sent.in_reply_to == 1
    assert sent.subject == "Re: Quote request FRA to ORD"
    assert "250.50 EUR" in sent.body
    assert h.writer.calls == 1
    assert h.store.outbox_status(1, Stage.QUOTED) == "sent"


async def test_own_mail_is_never_answered(tmp_path: Path) -> None:
    h = harness(tmp_path)
    h.mailbox.batches = [[mail(1, sender="wrathofcode@hackloop.mail")]]
    await h.orchestrator.poll_once()
    await drain(h)
    assert h.mailbox.sent == []
    assert h.extractor.calls == 0


async def test_duplicate_and_out_of_order_mail_is_answered_once(tmp_path: Path) -> None:
    h = harness(tmp_path)
    h.mailbox.batches = [[mail(2), mail(1, subject="Other"), mail(2)], [mail(2)]]
    await h.orchestrator.poll_once()
    await h.orchestrator.poll_once()
    await drain(h)
    assert sorted(m.in_reply_to for m in h.mailbox.sent) == [1, 2]


async def test_restart_never_resends(tmp_path: Path) -> None:
    first = harness(tmp_path)
    first.mailbox.batches = [[mail(1)]]
    await first.orchestrator.poll_once()
    await drain(first)
    first.store.close()
    second = harness(tmp_path)
    second.mailbox.batches = [[mail(1)]]
    await second.orchestrator.poll_once()
    await drain(second)
    assert second.mailbox.sent == []
    assert second.store.get_cursor() == 1


async def test_follow_up_in_thread_is_not_a_new_rfq(tmp_path: Path) -> None:
    h = harness(tmp_path)
    h.mailbox.batches = [
        [mail(1)],
        [mail(5, body="Thanks, also 200 kg FRA to ORD?", references=(1,), in_reply_to=1)],
    ]
    await h.orchestrator.poll_once()
    await drain(h)
    await h.orchestrator.poll_once()
    await drain(h)
    assert len(h.mailbox.sent) == 1
    assert h.extractor.calls == 1


@pytest.mark.parametrize(
    "sender",
    [
        "ratedesk@hackloop.mail",
        "tracking@hackloop.mail",
        "yellowtail-air-freight@hackloop.mail",
        "taunusfracht@hackloop.mail",
    ],
)
async def test_non_customer_mail_is_not_quoted(tmp_path: Path, sender: str) -> None:
    h = harness(tmp_path)
    h.mailbox.batches = [[mail(1, sender=sender)]]
    await h.orchestrator.poll_once()
    await drain(h)
    assert h.mailbox.sent == []
    assert h.extractor.calls == 0


async def test_second_quote_in_same_thread_is_blocked(tmp_path: Path) -> None:
    h = harness(tmp_path)
    h.mailbox.batches = [[mail(1)]]
    await h.orchestrator.poll_once()
    while h.orchestrator.tasks:
        await asyncio.gather(*list(h.orchestrator.tasks))
    quote = h.orchestrator.outbox.get_nowait()
    await h.orchestrator.send_quote(quote)
    await h.orchestrator.send_quote(quote)
    assert len(h.mailbox.sent) == 1


async def test_stale_rfq_is_skipped_without_llm(tmp_path: Path) -> None:
    h = harness(tmp_path, now=NOW + timedelta(minutes=7))
    h.mailbox.batches = [[mail(1)]]
    await h.orchestrator.poll_once()
    await drain(h)
    assert h.mailbox.sent == []
    assert h.extractor.calls == 0
    assert h.writer.calls == 0


async def test_kill_switch_sends_nothing_and_spends_nothing(tmp_path: Path) -> None:
    h = harness(tmp_path, settings=make_settings(tmp_path, kill_switch=True))
    h.mailbox.batches = [[mail(1)]]
    await h.orchestrator.poll_once()
    await drain(h)
    assert h.mailbox.sent == []
    assert h.extractor.calls == 0
    assert h.writer.calls == 0


async def test_door_rfq_without_pickup_price_is_held_at_hard_stop(tmp_path: Path) -> None:
    h = harness(tmp_path, pickup=FakePickup(None), door=True, now=NOW + timedelta(seconds=320))
    h.mailbox.batches = [[mail(1, received_at=NOW)]]
    await h.orchestrator.poll_once()
    await drain(h)
    assert h.mailbox.sent == []
    assert any(e.status.value == "hold" for e in h.sink.events)


async def test_door_rfq_adds_pickup_leg(tmp_path: Path) -> None:
    pickup = PickupPrice(
        source="trucker_email",
        trucker="Taunusfracht",
        zone="60",
        total=Decimal("85"),
        currency="EUR",
        received_at=NOW,
    )
    h = harness(tmp_path, pickup=FakePickup(pickup), door=True)
    h.mailbox.batches = [[mail(1)]]
    await h.orchestrator.poll_once()
    await drain(h)
    assert len(h.mailbox.sent) == 1
    assert "335.50 EUR" in h.mailbox.sent[0].body


async def test_send_retries_through_a_network_blip(tmp_path: Path) -> None:
    h = harness(tmp_path)
    calls = {"n": 0}
    original = h.mailbox.send

    async def flaky(outgoing: OutgoingMail) -> Mail:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("wifi down")
        return await original(outgoing)

    h.mailbox.send = flaky  # type: ignore[method-assign]
    h.mailbox.batches = [[mail(1)]]
    await h.orchestrator.poll_once()
    await drain(h)
    assert len(h.mailbox.sent) == 1
    assert calls["n"] == 2


async def test_sent_quote_is_never_repriced_or_overwritten(tmp_path: Path) -> None:
    # Round 27: a late re-pricing overwrote carrier, price and rate id after the quote was sent,
    # so the booking went to another airline with an expired rate.
    h = harness(tmp_path)
    h.mailbox.batches = [[mail(1)]]
    await h.orchestrator.poll_once()
    await drain(h)
    row = h.store._conn.execute("SELECT status, carrier, total FROM rfqs WHERE id='1'").fetchone()
    assert row[0] == Stage.QUOTED.value
    rfq, _ = await h.extractor.extract(mail(1))
    again = await h.orchestrator.build_quote(rfq, [], None)
    assert again is None
    assert h.store._conn.execute("SELECT status, carrier, total FROM rfqs WHERE id='1'").fetchone() == row
