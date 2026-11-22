"""Airline bids by email for lanes the portal does not serve (P8) and the rate desk
fallback when the portal answers 503 (P5).

At t=0 we send one bid request per airline serving the destination, but only when the
portal ports list has no such lane. Replies carry "[BID <rfq>-<tag>]" in the subject and
are turned into PriceOption(source="bid").
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from core.agents.directory import CarrierDirectory
from core.agents.trucker import NewMailSender
from core.contracts import RFQ, Mail, PriceOption
from sourcing.bids import Carrier, bid_ref, bid_request_email, parse_bid_reply

log = logging.getLogger("core.agents.airline_bids")

RATE_DESK_TAG = "RATEDESK"
SUBJECT_REF = re.compile(r"\[BID\s+([A-Z0-9_-]+)\]", re.IGNORECASE)
RATE_REF = re.compile(r"\b(R-[A-Za-z0-9_-]{8,40})\b")
# "Offer valid until: 21 Nov 2026 18:00 UTC" -> the quote can say "for about 12 minutes"
# instead of "for a short time" (5 of the last 13 quote emails said "a short time").
VALID_UNTIL = re.compile(
    r"valid\s+until:?\s*(\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\s+\d{1,2}:\d{2})\s*UTC", re.I
)


def offer_valid_until(body: str) -> datetime | None:
    found = VALID_UNTIL.search(body or "")
    if not found:
        return None
    try:
        return datetime.strptime(" ".join(found.group(1).split()), "%d %b %Y %H:%M").replace(tzinfo=UTC)
    except ValueError:
        return None
NOT_SERVED = re.compile(
    r"\b(?:do not|don't|does not|doesn't|cannot|can't)\s+serve\b|\bnot\s+served\b", re.IGNORECASE
)
TRANSIT = re.compile(r"transit(?:\s*time)?\s*[:=]?\s*(\d+)\s*(?:calendar\s+)?days?", re.IGNORECASE)

PortsLoader = Callable[[], Awaitable[Sequence[Any]]]


@dataclass(frozen=True)
class ParsedBid:
    total: Decimal
    currency: str
    transit_days: int


def parse_airline_reply(body: str) -> ParsedBid | None:
    """Price, currency and transit days from a bid reply. None for "do not serve" or no price."""
    text = body or ""
    if NOT_SERVED.search(text):
        return None
    quote = parse_bid_reply(text)
    if quote.declined or quote.total is None or quote.currency is None or quote.total <= 0:
        return None
    match = TRANSIT.search(text)
    transit = int(match.group(1)) if match else quote.transit_days
    if transit is None:
        return None
    return ParsedBid(total=quote.total, currency=quote.currency, transit_days=transit)


def bid_score(option: PriceOption, min_price: Decimal, min_transit: int) -> Decimal:
    """The brief's 50/50 carrier bid score: 0.5*price/min_price + 0.5*transit/min_transit."""
    transit = Decimal(max(option.transit_days, 1))
    return Decimal("0.5") * option.total / min_price + Decimal("0.5") * transit / max(
        min_transit, 1
    )


def best_by_score(options: Sequence[PriceOption]) -> PriceOption:
    """Lowest 50/50 score among bid options (same currency)."""
    if not options:
        raise ValueError("no bid options")
    min_price = min(o.total for o in options)
    min_transit = min(o.transit_days for o in options)
    return min(options, key=lambda o: (bid_score(o, min_price, min_transit), o.total, o.carrier))


@dataclass
class SentRequest:
    rfq_id: int
    carrier: str
    email: str
    answered: bool = False


def excluded_airlines(rfq: RFQ) -> list[str]:
    """Airlines the customer excluded (notes set by mail/exclusions.py). Round 42: we still sent
    Zephyr Steppe Cargo a bid request after the customer said not to offer it."""
    return [n.split(":", 1)[1].strip() for n in rfq.notes if n.startswith("exclude_carrier:")]


class AirlineBidSource:
    name = "airline_bid"

    def __init__(
        self,
        directory: CarrierDirectory,
        sender: NewMailSender,
        ports: PortsLoader,
        rate_desk: str = "ratedesk@hackloop.mail",
    ) -> None:
        self.directory = directory
        self.sender = sender
        self.ports = ports
        self.rate_desk = rate_desk.strip().lower()
        self._refs: dict[str, SentRequest] = {}
        self._sent_ids: dict[int, str] = {}
        self._options: dict[int, list[PriceOption]] = {}
        self._rate_desk_asked: set[int] = set()
        self._asked: set[int] = set()

    async def portal_serves(self, origin: str, destination: str) -> bool | None:
        try:
            lanes = await self.ports()
        except Exception as error:
            log.warning("bid_ports_failed", extra={"error": type(error).__name__})
            return None
        o, d = origin.upper(), destination.upper()
        return any(
            str(lane.origin).upper() == o and str(lane.destination).upper() == d for lane in lanes
        )

    async def request(self, rfq: RFQ) -> bool:
        """Email every airline serving the destination when the portal has no lane."""
        if rfq.mail_id in self._asked:
            return self.waiting(rfq.mail_id)
        served = await self.portal_serves(rfq.origin, rfq.destination)
        if served is not False:
            return False
        self._asked.add(rfq.mail_id)
        sent = 0
        from mail.exclusions import is_excluded

        banned = excluded_airlines(rfq)
        for contact in self.directory.airlines_serving(rfq.destination):
            if is_excluded(contact.name, None, banned):
                continue
            carrier = Carrier(name=contact.name, email=contact.email, kind="airline")
            ref = bid_ref(str(rfq.mail_id), carrier)
            subject, body = self._request_text(rfq, carrier, ref)
            if await self._send(rfq.mail_id, contact.name, contact.email, ref, subject, body):
                sent += 1
        log.info("airline_bids_sent", extra={"rfq": rfq.mail_id, "count": sent})
        return sent > 0

    async def request_lane(self, rfq: RFQ) -> bool:
        if rfq.mail_id in self._asked:
            return self.waiting(rfq.mail_id)
        try:
            lanes = await self.ports()
        except Exception:
            lanes = []
        o, d = rfq.origin.upper(), rfq.destination.upper()
        names = {
            str(getattr(airline, "name", "")).lower()
            for lane in lanes
            if str(lane.origin).upper() == o and str(lane.destination).upper() == d
            for airline in getattr(lane, "airlines", [])
        }
        serving = self.directory.airlines_serving(rfq.destination)
        contacts = [c for c in serving if c.name.lower() in names]
        if not lanes:
            # Round 45: the portal was down, so its lane list was empty and no airline was asked;
            # the quote went out from a rate sheet. Ask every airline the kit says serves the
            # destination instead.
            contacts = list(serving)
        if not contacts:
            return False
        self._asked.add(rfq.mail_id)
        sent = 0
        from mail.exclusions import is_excluded

        banned = excluded_airlines(rfq)
        for contact in contacts:
            if is_excluded(contact.name, None, banned):
                continue
            carrier = Carrier(name=contact.name, email=contact.email, kind="airline")
            ref = bid_ref(str(rfq.mail_id), carrier)
            subject, body = self._request_text(rfq, carrier, ref)
            if await self._send(rfq.mail_id, contact.name, contact.email, ref, subject, body):
                sent += 1
        log.info("lane_bids_sent", extra={"rfq": rfq.mail_id, "count": sent})
        return sent > 0

    async def request_rate_desk(self, rfq: RFQ) -> bool:
        """Once per RFQ: ask the rate desk for the lane when the portal is down."""
        if rfq.mail_id in self._rate_desk_asked:
            return False
        self._rate_desk_asked.add(rfq.mail_id)
        ref = f"{rfq.mail_id}-{RATE_DESK_TAG}"
        subject = f"[BID {ref}] Rate request {rfq.origin}-{rfq.destination}"
        body = "\n".join(
            [
                "Hello rate desk,",
                "",
                f"the portal is unavailable. Please send your all-in air freight rate "
                f"from {rfq.origin} to {rfq.destination} for {rfq.gross_kg} kg"
                + (f", {rfq.volume_cbm} cbm" if rfq.volume_cbm else "")
                + ", with the transit time in days.",
                f"Reference: {ref}",
                "",
                "Thank you,",
                "WRATHOFCODE",
            ]
        )
        return await self._send(rfq.mail_id, "rate desk", self.rate_desk, ref, subject, body)

    def _request_text(self, rfq: RFQ, carrier: Carrier, ref: str) -> tuple[str, str]:
        from core.agents.sourcing_adapter import to_shipment

        try:
            mail = bid_request_email(to_shipment(rfq), carrier, ref)
            return mail["subject"], mail["body"]
        except Exception as error:
            log.info("bid_template_fallback", extra={"error": type(error).__name__})
        subject = f"[BID {ref}] Air freight quote request {rfq.origin}-{rfq.destination}"
        body = (
            f"Hello {carrier.name} team,\n\nplease quote air freight {rfq.origin} -> "
            f"{rfq.destination}, {rfq.gross_kg} kg, airport to airport.\nReference: {ref}\n\n"
            "Please reply with the all-in price, currency and transit time in days.\n\n"
            "Thank you,\nWRATHOFCODE"
        )
        return subject, body

    async def _send(
        self, rfq_id: int, carrier: str, to: str, ref: str, subject: str, body: str
    ) -> bool:
        try:
            sent_id = await self.sender.send_new(to, subject, body)
        except Exception as error:
            log.warning("bid_request_failed", extra={"rfq": rfq_id, "error": type(error).__name__})
            return False
        self._refs[ref.upper()] = SentRequest(rfq_id=rfq_id, carrier=carrier, email=to.lower())
        if sent_id is not None:
            self._sent_ids[sent_id] = ref.upper()
        return True

    def _match(self, mail: Mail) -> str | None:
        if mail.in_reply_to is not None and mail.in_reply_to in self._sent_ids:
            return self._sent_ids[mail.in_reply_to]
        for ref_id in reversed(mail.references):
            if ref_id in self._sent_ids:
                return self._sent_ids[ref_id]
        match = SUBJECT_REF.search(mail.subject or "")
        if match and match.group(1).upper() in self._refs:
            return match.group(1).upper()
        return None

    def offer(self, mail: Mail) -> PriceOption | None:
        ref = self._match(mail)
        if ref is None:
            return None
        sent = self._refs[ref]
        sender = mail.sender.strip().lower()
        if sender != sent.email:
            return None
        sent.answered = True
        parsed = parse_airline_reply(mail.body)
        if parsed is None:
            log.info("bid_reply_ignored", extra={"rfq": sent.rfq_id, "mail": mail.id})
            return None
        carrier = sent.carrier
        if sent.email == self.rate_desk:
            carrier = self._named_airline(mail.body) or "rate desk"
        try:
            rate_ref = RATE_REF.search(mail.body or "")
            option = PriceOption(
                source="bid",
                carrier=carrier,
                rate_id=rate_ref.group(1) if rate_ref else None,
                rate_id_at=mail.received_at if rate_ref else None,
                valid_until=offer_valid_until(mail.body),
                total=parsed.total,
                currency=parsed.currency,
                transit_days=parsed.transit_days,
            )
        except ValidationError:
            log.info("bid_reply_invalid", extra={"rfq": sent.rfq_id, "mail": mail.id})
            return None
        self._options.setdefault(sent.rfq_id, []).append(option)
        log.info("bid_reply_stored", extra={"rfq": sent.rfq_id, "mail": mail.id})
        return option

    def _named_airline(self, body: str) -> str | None:
        lowered = body.lower()
        return next((c.name for c in self.directory.airlines() if c.name.lower() in lowered), None)

    def options(self, rfq_id: int) -> list[PriceOption]:
        return list(self._options.get(rfq_id, []))

    def requests(self, rfq_id: int) -> list[SentRequest]:
        return [s for s in self._refs.values() if s.rfq_id == rfq_id]

    def waiting(self, rfq_id: int) -> bool:
        """True while a bid request for this RFQ is still unanswered."""
        return any(not s.answered for s in self.requests(rfq_id))
