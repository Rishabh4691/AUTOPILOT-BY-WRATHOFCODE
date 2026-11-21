from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol, runtime_checkable

from pydantic import ValidationError

from core.agents.directory import CarrierDirectory
from core.contracts import RFQ, Mail, PickupPrice
from core.pricing.weight import volume_cbm

log = logging.getLogger("core.agents.trucker")

AMOUNT = r"(\d{1,3}(?:[.,' ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
CODES = r"(EUR|USD|GBP|CHF)"
SUBJECT_REF = re.compile(r"pickup request \d+( zone \S+)?", re.IGNORECASE)
SYMBOL_CODES = {"€": "EUR", "$": "USD", "£": "GBP"}
PRICE_PATTERNS = (
    re.compile(rf"\b{CODES}\s?{AMOUNT}", re.IGNORECASE),
    re.compile(rf"{AMOUNT}\s?(?:{CODES}\b|([€$£]))", re.IGNORECASE),
    re.compile(rf"([€$£])\s?{AMOUNT}"),
)


@runtime_checkable
class NewMailSender(Protocol):
    async def send_new(self, to: str, subject: str, body: str) -> int | None: ...


def parse_amount(text: str) -> Decimal | None:
    cleaned = text.replace(" ", "").replace("'", "")
    match = re.search(r"[.,](\d{1,2})$", cleaned)
    if match:
        whole = re.sub(r"[.,]", "", cleaned[: match.start()])
        cleaned = f"{whole}.{match.group(1)}"
    else:
        cleaned = re.sub(r"[.,]", "", cleaned)
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _currency(token: str) -> str:
    return SYMBOL_CODES.get(token, token.upper())


def _candidates(text: str) -> list[tuple[int, str, str]]:
    found: list[tuple[int, str, str]] = []
    first, second, third = PRICE_PATTERNS
    for m in first.finditer(text):
        found.append((m.start(), m.group(2), _currency(m.group(1))))
    for m in second.finditer(text):
        found.append((m.start(), m.group(1), _currency(m.group(2) or m.group(3))))
    for m in third.finditer(text):
        found.append((m.start(), m.group(2), _currency(m.group(1))))
    return sorted(found)


def parse_price(text: str) -> tuple[Decimal, str] | None:
    for _, amount_text, currency in _candidates(text):
        amount = parse_amount(amount_text)
        if amount is not None and amount > 0:
            return amount, currency
    return None


def shipment_lines(rfq: RFQ) -> list[str]:
    pieces = sum(piece.count for piece in rfq.pieces)
    if not pieces:
        noted = [n[8:] for n in rfq.notes if n.startswith("pieces: ") and n[8:].isdigit()]
        pieces = int(noted[0]) if noted else 0
    cbm = volume_cbm(rfq.pieces) if rfq.pieces else rfq.volume_cbm
    lines = [f"Pieces: {pieces or 'see volume'}. Gross weight: {rfq.gross_kg} kg."]
    if cbm:
        lines.append(f"Volume: {cbm.quantize(Decimal('0.01'))} cbm.")
    for piece in rfq.pieces:
        lines.append(
            f"Dimensions: {piece.count} x {piece.length_cm} x {piece.width_cm} x "
            f"{piece.height_cm} cm."
        )
    return lines


def pickup_postcode(rfq: RFQ) -> str | None:
    for note in rfq.notes:
        if note.startswith("postcode: ") and note[10:].isdigit():
            return note[10:]
    return None


def request_body(rfq: RFQ, zone: str, area: str, airport: str) -> str:
    ready = rfq.ready_date.isoformat() if rfq.ready_date else "as soon as possible"
    postcode = pickup_postcode(rfq)
    where = f"postcode {postcode} {area}" if postcode else f"zone {zone} ({area})"
    return "\n".join(
        [
            "Hello,",
            "",
            f"Please quote a pickup from {where} to {airport} airport.",
            f"Pickup postcode: {postcode or zone}.",
            *shipment_lines(rfq),
            f"Ready date: {ready}.",
            f"Please reply with your all-in price and keep 'Pickup request {rfq.mail_id}' "
            "in the subject.",
            "",
            "Best regards,",
            "WRATHOFCODE Air Freight",
        ]
    )


class EmailTruckerPickupSource:
    name = "trucker_email"

    def __init__(
        self,
        directory: CarrierDirectory,
        sender: NewMailSender,
        now: Callable[[], datetime],
    ) -> None:
        self.directory = directory
        self.sender = sender
        self.now = now
        self._asked: dict[int, set[str]] = {}
        self._zones: dict[int, str] = {}
        self._sent_ids: dict[int, int] = {}
        self._prices: dict[int, list[PickupPrice]] = {}

    async def request(self, rfq: RFQ) -> None:
        if not rfq.door_pickup or not rfq.pickup_zone or rfq.mail_id in self._asked:
            return
        zone_code = rfq.pickup_zone.strip()
        zone = self.directory.zone(zone_code)
        airport = zone.airport if zone else rfq.origin
        area = zone.area if zone else f"zone {zone_code}"
        subject = f"Pickup request {rfq.mail_id} zone {zone_code} to {airport}"
        body = request_body(rfq, zone_code, area, airport)
        self._asked[rfq.mail_id] = set()
        self._zones[rfq.mail_id] = zone_code
        for trucker in self.directory.truckers_for_zone(zone_code):
            await self._send(rfq.mail_id, trucker.email, subject, body)

    async def _send(self, rfq_id: int, to: str, subject: str, body: str) -> None:
        try:
            sent_id = await self.sender.send_new(to, subject, body)
        except Exception as error:
            log.warning(
                "trucker_request_failed", extra={"rfq": rfq_id, "error": type(error).__name__}
            )
            return
        self._asked[rfq_id].add(to.lower())
        if sent_id is not None:
            self._sent_ids[sent_id] = rfq_id
        log.info("trucker_request_sent", extra={"rfq": rfq_id, "length": len(body)})

    def _rfq_for(self, mail: Mail) -> int | None:
        sender = mail.sender.strip().lower()
        if mail.in_reply_to is not None:
            rfq_id = self._sent_ids.get(mail.in_reply_to)
            if rfq_id is not None and sender in self._asked.get(rfq_id, set()):
                return rfq_id
        for rfq_id, asked in self._asked.items():
            if sender in asked and re.search(
                rf"pickup request {rfq_id}\b", mail.subject, re.IGNORECASE
            ):
                return rfq_id
        return None

    def offer(self, mail: Mail) -> None:
        rfq_id = self._rfq_for(mail)
        if rfq_id is None:
            return
        parsed = parse_price(mail.body) or parse_price(SUBJECT_REF.sub(" ", mail.subject))
        if parsed is None:
            log.info("trucker_offer_unparsed", extra={"rfq": rfq_id, "mail": mail.id})
            return
        contact = self.directory.by_email(mail.sender)
        try:
            price = PickupPrice(
                source=self.name,
                trucker=contact.name if contact else mail.sender.strip().lower(),
                zone=self._zones[rfq_id],
                total=parsed[0],
                currency=parsed[1],
                received_at=mail.received_at,
            )
        except ValidationError:
            log.info("trucker_offer_invalid", extra={"rfq": rfq_id, "mail": mail.id})
            return
        self._prices.setdefault(rfq_id, []).append(price)
        log.info("trucker_offer_stored", extra={"rfq": rfq_id, "mail": mail.id})

    async def collect(self, rfq: RFQ) -> PickupPrice | None:
        prices = self._prices.get(rfq.mail_id)
        if not prices:
            return None
        currency = prices[0].currency
        return min((p for p in prices if p.currency == currency), key=lambda p: p.total)
