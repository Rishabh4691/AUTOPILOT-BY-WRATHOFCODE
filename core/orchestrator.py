from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from core.agents.limits import FREIGHTER_ONLY_CM, tallest
from core.agents.limits import usable as fit_limits
from core.config import Settings
from core.contracts import (
    RFQ,
    Agent,
    EmailWriter,
    Event,
    EventSink,
    EventStatus,
    ExtractionError,
    LlmUsage,
    Mail,
    MailboxClient,
    MailClassifier,
    MailKind,
    OutgoingMail,
    PickupPrice,
    PickupSource,
    PortalDown,
    PriceOption,
    PriceSource,
    Quote,
    RfqExtractor,
    SourceUnavailable,
    Stage,
    to_money,
)
from core.pricing.selection import select
from core.store import Store
from core.timing import TimingPolicy, decide, is_stale
from mail.writer import arrival_date

log = logging.getLogger("core.orchestrator")

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def reply_subject(subject: str) -> str:
    clean = subject.strip()
    return clean if clean.lower().startswith("re:") else f"Re: {clean}".strip()


def review_facts(
    rfq: RFQ, options: list[PriceOption], pickup: PickupPrice | None
) -> dict[str, Any]:
    return {
        "received_at_epoch": rfq.received_at.timestamp(),
        "origin": rfq.origin,
        "destination": rfq.destination,
        "gross_kg": str(rfq.gross_kg),
        "volume_cbm": None if rfq.volume_cbm is None else str(rfq.volume_cbm),
        "pieces": len(rfq.pieces),
        "door_pickup": rfq.door_pickup,
        "pickup_zone": rfq.pickup_zone,
        "preference": rfq.preference.value,
        "currency": rfq.currency,
        "pickup_total": None
        if pickup is None
        else f"{pickup.total} {pickup.currency} {pickup.trucker}",
        "options": [
            f"{o.source} {o.carrier} {o.total} {o.currency} {o.transit_days}d"
            for o in sorted(options, key=lambda o: (o.total, o.transit_days))
        ],
    }


def dg_request_body(rfq: RFQ, declared: str) -> str:
    return (
        f"Hello,\n\nthank you for your request from {rfq.origin} to {rfq.destination}. "
        f"Your documents show dangerous goods ({declared}), so before we can quote and book "
        "the airline needs a few documents from you:\n\n"
        "- the Shipper's Declaration for Dangerous Goods\n"
        "- the safety data sheet (MSDS) for the product\n"
        "- the UN number, class and packing group as packed\n\n"
        "As soon as we have them we will send you an all-in price straight away.\n\n"
        f"Best regards,\nLena\nWRATHOFCODE Air Freight"
    )


BID_CUTOFF_S = 75.0


def portal_first(options: list[PriceOption]) -> list[PriceOption]:
    portal = [option for option in options if option.source == "portal"]
    bids = [option for option in options if option.source == "bid"]
    return portal or bids or options


def convert_money(amount: Decimal, source: str, target: str) -> Decimal | None:
    if source == target:
        return amount
    from sourcing import fx

    source_rate, target_rate = fx.get_rate(source), fx.get_rate(target)
    if source_rate is None or target_rate is None or target_rate == 0:
        return None
    return to_money(amount * source_rate / target_rate)


def quote_currency(rfq: RFQ, options: list[PriceOption]) -> str:
    currencies = {option.currency for option in options}
    if rfq.currency:
        return rfq.currency
    return "EUR" if "EUR" in currencies or not currencies else sorted(currencies)[0]


def in_currency(options: list[PriceOption], target: str) -> list[PriceOption]:
    converted: list[PriceOption] = []
    for option in options:
        total = convert_money(option.total, option.currency, target)
        if total is not None:
            converted.append(option.model_copy(update={"total": total, "currency": target}))
    if converted:
        return converted
    fallback = sorted({option.currency for option in options})[0]
    return [option for option in options if option.currency == fallback]


@dataclass
class SourcingState:
    options: list[PriceOption] = field(default_factory=list)
    pending: set[str] = field(default_factory=set)
    reply_seconds: dict[str, float] = field(default_factory=dict)


@dataclass
class Orchestrator:
    settings: Settings
    store: Store
    mailbox: MailboxClient
    classifier: MailClassifier
    extractor: RfqExtractor
    sources: Sequence[PriceSource]
    pickup: PickupSource | None
    writer: EmailWriter
    events: EventSink
    clock: Clock = utc_now
    tick_s: float = 1.0
    outbox: asyncio.Queue[Quote] = field(default_factory=asyncio.Queue)
    tasks: set[asyncio.Task[None]] = field(default_factory=set)
    booker: Any = None
    tracker: Any = None
    dg: Any = None
    tariffs: Any = None
    attachments: Any = None
    review_dir: Path | None = None
    review_deadline_s: float = 110.0
    review_context: dict[int, dict[str, Any]] = field(default_factory=dict)
    bids: Any = None

    @property
    def policy(self) -> TimingPolicy:
        return TimingPolicy(
            send_at_s=self.settings.send_at_s,
            wait_until_s=self.settings.wait_until_s,
            hard_stop_s=self.settings.hard_stop_s,
        )

    def emit(
        self,
        agent: Agent,
        step: str,
        status: EventStatus,
        message: str,
        rfq_id: int | None = None,
        cost: Decimal | None = None,
        duration_ms: int | None = None,
        data: dict[str, str | int | float | bool | None] | None = None,
    ) -> None:
        self.events.emit(
            Event(
                ts=self.clock(),
                agent=agent,
                step=step,
                status=status,
                message=message,
                rfq_id=None if rfq_id is None else str(rfq_id),
                llm_cost_usd=cost or Decimal("0"),
                duration_ms=duration_ms,
                data=data or {},
            )
        )

    async def poll_once(self) -> int:
        since_id = self.store.get_cursor()
        mails, next_since_id = await self.mailbox.poll(since_id)
        for problem in getattr(self.mailbox, "last_shape_errors", []):
            self.emit(
                Agent.ROUTER, "poll", EventStatus.WARN, f"A mail had an unexpected shape: {problem}"
            )
        for mail in sorted(mails, key=lambda m: m.id):
            self.route(mail)
        self.store.set_cursor(max(next_since_id, since_id))
        return len(mails)

    def route(self, mail: Mail) -> None:
        classification = self.classifier.classify(mail, self.store.known_rfq_threads())
        if not self.store.mark_seen(mail, classification.kind):
            return
        kind = classification.kind
        if kind is MailKind.RFQ:
            self.accept_rfq(mail)
            return
        if self.dg is not None and kind is MailKind.FOLLOW_UP:
            task = asyncio.create_task(self.dg.on_reply(self, mail), name=f"dg-{mail.id}")
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        if self.booker is not None and kind in (MailKind.FOLLOW_UP, MailKind.BOOKING_CONFIRMATION):
            task = asyncio.create_task(self.booker.handle(self, mail, kind), name=f"book-{mail.id}")
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        if kind is MailKind.PORTAL_REPLY:
            for source in self.sources:
                on_mail = getattr(source, "on_mail", None)
                if callable(on_mail):
                    on_mail(mail)
        if self.tracker is not None and kind is MailKind.TRACKING:
            task = asyncio.create_task(self.tracker.handle(self, mail), name=f"track-{mail.id}")
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        if self.tariffs is not None and kind is MailKind.TARIFF and mail.attachments:
            task = asyncio.create_task(self.tariffs.handle(self, mail), name=f"tariff-{mail.id}")
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        if kind in (MailKind.CARRIER_BID, MailKind.PORTAL_REPLY) and self.bids is not None:
            self.bids.offer(mail)
        if kind is MailKind.TRUCKER_BID and self.pickup is not None:
            offer = getattr(self.pickup, "offer", None)
            if callable(offer):
                offer(mail)
        self.emit(
            Agent.ROUTER,
            "route",
            EventStatus.INFO,
            f"Mail {mail.id} sorted as {kind.value.replace('_', ' ')}: {classification.reason}",
            rfq_id=mail.thread_root_id if kind is MailKind.FOLLOW_UP else None,
        )

    def accept_rfq(self, mail: Mail) -> None:
        if is_stale(mail.received_at, self.clock(), self.settings.rfq_lifetime_s):
            self.store.upsert_rfq(
                str(mail.id),
                str(mail.thread_root_id),
                mail.sender,
                mail.subject,
                mail.received_at,
                Stage.SKIPPED.value,
            )
            self.emit(
                Agent.RFQ,
                "stale",
                EventStatus.WARN,
                f"Request {mail.id} is older than six minutes. Skipped.",
                mail.id,
            )
            return
        self.store.register_rfq_thread(mail.thread_root_id, mail.id, mail.sender)
        self.store.upsert_rfq(
            str(mail.id),
            str(mail.thread_root_id),
            mail.sender,
            mail.subject,
            mail.received_at,
            Stage.NEW.value,
        )
        self.emit(
            Agent.RFQ,
            "new",
            EventStatus.INFO,
            f"New quote request {mail.id} from {mail.sender}.",
            mail.id,
        )
        task = asyncio.create_task(self.handle_rfq(mail), name=f"rfq-{mail.id}")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def elapsed_s(self, rfq_received_at: datetime) -> float:
        return (self.clock() - rfq_received_at).total_seconds()

    async def handle_rfq(self, mail: Mail) -> None:
        try:
            await self.process_rfq(mail)
        except Exception as error:
            log.exception("rfq_failed", extra={"rfq": mail.id})
            self.hold(
                mail.id,
                f"Request {mail.id} failed unexpectedly ({type(error).__name__}). "
                "A person should price it.",
            )

    def hold(self, rfq_id: int, message: str) -> None:
        self.store.update_rfq(str(rfq_id), status=Stage.HELD.value)
        self.emit(Agent.RFQ, "hold", EventStatus.HOLD, message, rfq_id)

    async def process_rfq(self, mail: Mail) -> None:
        if self.settings.kill_switch:
            self.hold(mail.id, "Kill switch is on. Nothing is priced or sent.")
            return
        try:
            rfq, usage = await self.extractor.extract(mail)
        except ExtractionError as error:
            self.hold(mail.id, f"Could not read request {mail.id}: {error}")
            return
        extract_cost = self.record_usage(mail.id, "extract", usage)
        self.store.update_rfq(
            str(mail.id),
            status=Stage.EXTRACTED.value,
            origin=rfq.origin,
            destination=rfq.destination,
            preference=rfq.preference.value,
        )
        self.emit(
            Agent.RFQ,
            "extracted",
            EventStatus.OK,
            f"Request {mail.id}: {rfq.origin} to {rfq.destination}, {rfq.gross_kg} kg, "
            f"{'door pickup' if rfq.door_pickup else 'airport to airport'}, "
            f"{rfq.preference.value}.",
            mail.id,
            cost=extract_cost,
        )
        if self.dg is not None:
            try:
                if await self.dg.stop_for_docs(self, mail):
                    return
            except Exception:
                log.exception("dg_check_failed", extra={"rfq": mail.id})
        elif await self.dangerous_goods_blocked(mail, rfq):
            return
        quote = await self.source_and_price(rfq)
        if quote is not None:
            await self.outbox.put(quote)

    async def dangerous_goods_blocked(self, mail: Mail, rfq: RFQ) -> bool:
        from core.agents.attachments import dangerous_goods, has_dg_documents
        from mail.text import fresh_text

        attached = ""
        if self.attachments is not None and mail.attachments:
            try:
                attached = await self.attachments.text(mail)
            except Exception:
                log.exception("attachment_read_failed")
        # Quoted history describes older shipments; only the new mail and its attachments count.
        declared = dangerous_goods(f"{fresh_text(mail.body)}\n{attached}")
        if declared is None or has_dg_documents(mail):
            return False
        if not self.store.claim_outbox(rfq.thread_root_id, Stage.HELD, rfq.mail_id, self.clock()):
            return True
        body = dg_request_body(rfq, declared)
        outgoing = OutgoingMail(
            to=rfq.customer, subject=reply_subject(rfq.subject), body=body, in_reply_to=rfq.mail_id
        )
        try:
            sent = await self.mailbox.send(outgoing)
        except Exception as error:
            self.store.mark_outbox_failed(rfq.thread_root_id, Stage.HELD, type(error).__name__)
            self.hold(rfq.mail_id, f"Dangerous goods ({declared}); asking for documents failed.")
            return True
        self.store.mark_outbox_sent(rfq.thread_root_id, Stage.HELD, sent.id)
        self.store.update_rfq(str(rfq.mail_id), status=Stage.HELD.value, email_body=body)
        self.emit(
            Agent.RFQ,
            "dangerous_goods",
            EventStatus.HOLD,
            f"Request {rfq.mail_id} declares dangerous goods ({declared}) without documents. "
            "Asked the customer for the shipper's declaration and safety data sheet.",
            rfq.mail_id,
        )
        return True

    def record_usage(self, rfq_id: int, step: str, usage: LlmUsage | None) -> Decimal:
        if usage is None:
            return Decimal("0")
        log.info(
            "llm_usage",
            extra={
                "rfq": rfq_id,
                "step": step,
                "model": usage.model,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost_usd": str(usage.cost_usd),
            },
        )
        return usage.cost_usd or Decimal("0")

    async def run_source(
        self, source: PriceSource, rfq: RFQ, state: SourcingState, started: float
    ) -> None:
        try:
            options = await source.quote(rfq)
        except PortalDown as error:
            self.emit(
                Agent.RFQ,
                "source",
                EventStatus.WARN,
                f"{source.name} answered 503: {error}. Asking the rate desk.",
                rfq.mail_id,
            )
            options = []
            await self.ask_rate_desk(rfq)
        except SourceUnavailable as error:
            self.emit(
                Agent.RFQ,
                "source",
                EventStatus.WARN,
                f"{source.name} is unavailable: {error}",
                rfq.mail_id,
            )
            options = []
        except Exception as error:
            log.exception("source_failed", extra={"source": source.name})
            self.emit(
                Agent.RFQ,
                "source",
                EventStatus.WARN,
                f"{source.name} failed ({type(error).__name__}).",
                rfq.mail_id,
            )
            options = []
        finally:
            state.pending.discard(source.name)
            state.reply_seconds[source.name] = round(time.monotonic() - started, 2)
        state.options.extend(options)
        self.emit(
            Agent.RFQ,
            "source",
            EventStatus.INFO,
            f"{source.name} returned {len(options)} prices "
            f"in {state.reply_seconds[source.name]} seconds.",
            rfq.mail_id,
            duration_ms=int(state.reply_seconds[source.name] * 1000),
        )

    async def source_and_price(self, rfq: RFQ) -> Quote | None:
        self.store.update_rfq(str(rfq.mail_id), status=Stage.SOURCING.value)
        state = SourcingState(pending={source.name for source in self.sources})
        started = time.monotonic()
        if rfq.door_pickup and self.pickup is not None:
            try:
                await self.pickup.request(rfq)
            except Exception as error:
                log.exception("pickup_request_failed")
                self.emit(
                    Agent.RFQ,
                    "pickup",
                    EventStatus.WARN,
                    f"Pickup request failed ({type(error).__name__}).",
                    rfq.mail_id,
                )
        await self.request_bids(rfq)
        runners = [
            asyncio.create_task(self.run_source(s, rfq, state, started)) for s in self.sources
        ]
        try:
            return await self.wait_and_build(rfq, state)
        finally:
            for runner in runners:
                runner.cancel()

    async def request_bids(self, rfq: RFQ) -> None:
        if self.bids is None:
            return
        try:
            if await self.bids.request(rfq):
                self.emit(
                    Agent.RFQ,
                    "bids",
                    EventStatus.INFO,
                    f"{rfq.origin}-{rfq.destination} is not on the portal. "
                    f"Asked {len(self.bids.requests(rfq.mail_id))} airlines for a bid.",
                    rfq.mail_id,
                )
        except Exception as error:
            log.exception("bid_request_failed")
            self.emit(
                Agent.RFQ,
                "bids",
                EventStatus.WARN,
                f"Airline bid requests failed ({type(error).__name__}).",
                rfq.mail_id,
            )

    async def ask_rate_desk(self, rfq: RFQ) -> None:
        if self.bids is None:
            return
        try:
            await self.bids.request_lane(rfq)
        except Exception:
            log.exception("lane_bid_request_failed")
        if not any(getattr(source, "name", "") == "ratedesk" for source in self.sources):
            try:
                await self.bids.request_rate_desk(rfq)
            except Exception:
                log.exception("rate_desk_request_failed")

    def all_options(self, rfq: RFQ, state: SourcingState) -> list[PriceOption]:
        if self.bids is None:
            return list(state.options)
        return [*state.options, *self.bids.options(rfq.mail_id)]

    def pending_sources(self, rfq: RFQ, state: SourcingState) -> frozenset[str]:
        pending = set(state.pending)
        priced = [o for o in state.options if o.source == "portal"]
        if self.bids is not None and not priced and self.bids.waiting(rfq.mail_id):
            pending.add(self.bids.name)
        if self.elapsed_s(rfq.received_at) >= BID_CUTOFF_S and self.all_options(rfq, state):
            pending -= {"ratedesk", getattr(self.bids, "name", "bids")}
        return frozenset(pending)

    async def wait_and_build(self, rfq: RFQ, state: SourcingState) -> Quote | None:
        warned = False
        while True:
            pickup = await self.current_pickup(rfq)
            elapsed = self.elapsed_s(rfq.received_at)
            options = self.all_options(rfq, state)
            if pickup is None and rfq.door_pickup and options:
                late = elapsed >= self.policy.wait_until_s
                if late:
                    estimate = getattr(self.pickup, "estimate", None)
                    guess = estimate(rfq) if callable(estimate) else None
                    if guess is not None:
                        self.emit(
                            Agent.RFQ,
                            "pickup_estimate",
                            EventStatus.WARN,
                            f"No trucker price for request {rfq.mail_id} after {int(elapsed)} s. "
                            f"Quoting with the cheapest earlier offer for this zone ({guess.total} EUR).",
                            rfq.mail_id,
                        )
                        return await self.build_quote(rfq, options, guess)
            if (
                not warned
                and elapsed >= 180
                and (not options or (rfq.door_pickup and pickup is None))
            ):
                warned = True
                self.emit(
                    Agent.RFQ,
                    "late",
                    EventStatus.HOLD,
                    f"Request {rfq.mail_id} has no quote after 3 minutes "
                    f"({'no price' if not options else 'no pickup price'}). Take over now.",
                    rfq.mail_id,
                )
            verdict = decide(
                self.policy,
                elapsed_s=self.elapsed_s(rfq.received_at),
                pending_sources=self.pending_sources(rfq, state),
                have_option=bool(options),
                pending_can_win=True,
                needs_pickup=rfq.door_pickup,
                have_pickup=pickup is not None,
            )
            if verdict == "hold":
                reason = "no price arrived" if not options else "no pickup price arrived"
                self.hold(
                    rfq.mail_id, f"Request {rfq.mail_id} is on hold: {reason} before the deadline."
                )
                return None
            if verdict == "send":
                return await self.build_quote(rfq, options, pickup)
            await asyncio.sleep(self.tick_s)

    async def current_pickup(self, rfq: RFQ) -> PickupPrice | None:
        if not rfq.door_pickup or self.pickup is None:
            return None
        return await self.pickup.collect(rfq)

    async def build_quote(
        self, rfq: RFQ, options: list[PriceOption], pickup: PickupPrice | None
    ) -> Quote | None:
        options, dropped = fit_limits(options, rfq)
        for reason in dropped:
            self.emit(Agent.RFQ, "limits", EventStatus.INFO, f"Skipped {reason}.", rfq.mail_id)
        high = tallest(rfq)
        if high is not None and high > FREIGHTER_ONLY_CM:
            self.emit(
                Agent.RFQ,
                "oversize",
                EventStatus.WARN,
                f"Request {rfq.mail_id} has a {high} cm piece: freighter only, check the airline.",
                rfq.mail_id,
            )
        options = portal_first(options)
        usable = in_currency(options, quote_currency(rfq, options))
        option = select(usable, rfq.preference)
        self.review_context[rfq.mail_id] = review_facts(rfq, usable, pickup)
        total = option.total
        if pickup is not None and pickup.currency != option.currency:
            converted = convert_money(pickup.total, pickup.currency, option.currency)
            if converted is not None:
                pickup = pickup.model_copy(update={"total": converted, "currency": option.currency})
        if pickup is not None:
            if pickup.currency != option.currency:
                self.hold(
                    rfq.mail_id,
                    f"Pickup is in {pickup.currency} but the flight is in {option.currency}. "
                    "A person should convert it.",
                )
                return None
            total = to_money(total + pickup.total)
        if rfq.currency is not None and rfq.currency != option.currency:
            self.emit(
                Agent.RFQ,
                "currency",
                EventStatus.WARN,
                f"Customer asked for {rfq.currency}; we quote {option.currency}.",
                rfq.mail_id,
            )
        self.store.update_rfq(
            str(rfq.mail_id),
            status=Stage.PRICED.value,
            carrier=option.carrier,
            total=total,
            currency=option.currency,
            rate_id=option.rate_id,
            breakdown_json=json.dumps(
                {
                    "flight": str(option.total),
                    "pickup": None if pickup is None else str(pickup.total),
                    "transit_days": option.transit_days,
                    "source": option.source,
                    "carrier_code": option.carrier_code,
                    "origin": rfq.origin,
                    "destination": rfq.destination,
                    "valid_until": None
                    if option.valid_until is None
                    else option.valid_until.isoformat(),
                    "ready_date": None if rfq.ready_date is None else rfq.ready_date.isoformat(),
                    "arrival": arrival_date(rfq.ready_date, option.transit_days).isoformat(),
                }
            ),
        )
        self.emit(
            Agent.RFQ,
            "priced",
            EventStatus.OK,
            f"Request {rfq.mail_id}: {option.carrier}, {total} {option.currency}, "
            f"{option.transit_days} days.",
            rfq.mail_id,
        )
        if self.settings.kill_switch:
            self.hold(rfq.mail_id, "Kill switch is on. Nothing is sent.")
            return None
        body, usage = await self.writer.write(rfq, option, total, option.currency)
        self.record_usage(rfq.mail_id, "write", usage)
        to = self.store.rfq_thread_customer(rfq.thread_root_id) or rfq.customer
        return Quote(
            rfq_mail_id=rfq.mail_id,
            thread_root_id=rfq.thread_root_id,
            to=to,
            subject=reply_subject(rfq.subject),
            option=option,
            pickup=pickup,
            total=total,
            currency=option.currency,
            body=body,
            used_llm=usage is not None,
            usage=usage,
        )

    def review_enabled(self) -> bool:
        return self.review_dir is not None and (self.review_dir.parent / "REVIEW_ON").exists()

    async def await_review(self, quote: Quote) -> Quote | None:
        if not self.review_enabled() or self.review_dir is None:
            return quote
        self.review_dir.mkdir(parents=True, exist_ok=True)
        draft_path = self.review_dir / f"{quote.rfq_mail_id}.json"
        decision_path = self.review_dir / f"{quote.rfq_mail_id}.decision.json"
        facts = self.review_context.pop(quote.rfq_mail_id, {})
        received = facts.get("received_at_epoch")
        deadline = (
            float(received) + self.review_deadline_s if received is not None else time.time() + 60.0
        )
        draft = {
            "rfq": quote.rfq_mail_id,
            "to": quote.to,
            "subject": quote.subject,
            "total": str(quote.total),
            "currency": quote.currency,
            "carrier": quote.option.carrier,
            "transit_days": quote.option.transit_days,
            "source": quote.option.source,
            "pickup": None if quote.pickup is None else str(quote.pickup.total),
            "auto_send_at": deadline,
            "facts": facts,
            "body": quote.body,
        }
        draft_path.write_text(json.dumps(draft, indent=1, default=str), encoding="utf-8")
        log.info(
            "review_pending",
            extra={
                "rfq": quote.rfq_mail_id,
                "total": str(quote.total),
                "currency": quote.currency,
                "carrier": quote.option.carrier,
                "seconds_left": round(deadline - time.time()),
            },
        )
        while time.time() < deadline:
            if decision_path.exists():
                try:
                    decision = json.loads(decision_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    await asyncio.sleep(0.5)
                    continue
                action = str(decision.get("action", "send"))
                log.info("review_decided", extra={"rfq": quote.rfq_mail_id, "action": action})
                if action == "hold":
                    return None
                body = decision.get("body")
                updates: dict[str, Any] = {}
                if isinstance(body, str) and body.strip():
                    updates["body"] = body
                if decision.get("total") and decision.get("currency"):
                    updates["total"] = Decimal(str(decision["total"]))
                    updates["currency"] = str(decision["currency"])
                return quote.model_copy(update=updates) if updates else quote
            await asyncio.sleep(1.0)
        log.info("review_timeout_autosend", extra={"rfq": quote.rfq_mail_id})
        return quote

    async def send_quote(self, quote: Quote) -> None:
        if self.settings.kill_switch:
            self.hold(quote.rfq_mail_id, "Kill switch is on. Nothing is sent.")
            return
        if not self.store.claim_outbox(
            quote.thread_root_id, Stage.QUOTED, quote.rfq_mail_id, self.clock()
        ):
            self.emit(
                Agent.RFQ,
                "send",
                EventStatus.WARN,
                f"Thread {quote.thread_root_id} already has a quote. Not sending again.",
                quote.rfq_mail_id,
            )
            return
        reviewed = await self.await_review(quote)
        if reviewed is None:
            self.store.mark_outbox_failed(quote.thread_root_id, Stage.QUOTED, "held by reviewer")
            self.hold(
                quote.rfq_mail_id, f"Reviewer held the quote for request {quote.rfq_mail_id}."
            )
            return
        quote = reviewed
        outgoing = OutgoingMail(
            to=quote.to, subject=quote.subject, body=quote.body, in_reply_to=quote.rfq_mail_id
        )
        try:
            sent = await self.mailbox.send(outgoing)
        except Exception as error:
            self.store.mark_outbox_failed(quote.thread_root_id, Stage.QUOTED, type(error).__name__)
            log.exception("send_failed")
            self.hold(
                quote.rfq_mail_id,
                f"Sending the quote for request {quote.rfq_mail_id} failed "
                f"({type(error).__name__}).",
            )
            return
        self.store.mark_outbox_sent(quote.thread_root_id, Stage.QUOTED, sent.id)
        self.store.update_rfq(
            str(quote.rfq_mail_id),
            status=Stage.QUOTED.value,
            quoted_at=self.clock(),
            email_body=quote.body,
        )
        verb = "Would send" if self.settings.dry_run else "Sent"
        self.emit(
            Agent.RFQ,
            "quoted",
            EventStatus.OK,
            f"{verb} quote for request {quote.rfq_mail_id}: {quote.total} {quote.currency}, "
            f"{'one model call made' if quote.used_llm else 'no model call'}.",
            quote.rfq_mail_id,
            cost=None if quote.usage is None else quote.usage.cost_usd,
            data={"dry_run": self.settings.dry_run},
        )

    async def sender_worker(self) -> None:
        while True:
            quote = await self.outbox.get()
            try:
                await self.send_quote(quote)
            finally:
                self.outbox.task_done()
