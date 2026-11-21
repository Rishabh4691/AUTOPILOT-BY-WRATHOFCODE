from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx
from pydantic import ValidationError

from core.agents.directory import CarrierDirectory
from core.contracts import RFQ, Mail, PickupPrice
from core.pricing.weight import volume_cbm

PICKUP_GRACE_S = 8.0
MAX_PICKUP_HOURS = 24.0
PICKUP_HOURS = re.compile(
    r"(?:pick ?up|collection|abholung|enlèvement|recogida|ritiro)\s*(?:time|within|in|zeit|délai|plazo)?\s*[:=]?\s*"
    r"(?:within\s*)?(\d{1,3}(?:[.,]\d)?)\s*(?:h\b|hours?|hrs?|stunden|heures|horas|ore)",
    re.I,
)


def pickup_hours(text: str) -> float | None:
    m = PICKUP_HOURS.search(text or "")
    return float(m.group(1).replace(",", ".")) if m else None


PICKUP_WAIT_S = 50.0

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
    field = getattr(rfq, "pickup_postcode", None)
    if field:
        return str(field)
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
        history_path: Path | None = None,
    ) -> None:
        self.directory = directory
        self.sender = sender
        self.now = now
        self.history_path = history_path
        self._asked: dict[int, set[str]] = {}
        self._hours: dict[tuple[int, str], float | None] = {}
        self._answered: dict[int, set[str]] = {}
        self._first_price_at: dict[int, float] = {}
        self._zones: dict[int, str] = {}
        self._sent_ids: dict[int, int] = {}
        self._prices: dict[int, list[PickupPrice]] = {}

    def fallback_zone(self, rfq: RFQ) -> str | None:
        zones = [z for z in self.directory.zones if z.airport == rfq.origin]
        served = [z for z in zones if self.directory.truckers_for_zone(z.zone)]
        return (served or zones)[0].zone if (served or zones) else None

    async def request(self, rfq: RFQ) -> None:
        if not rfq.door_pickup or rfq.mail_id in self._asked:
            return
        zone_code = (rfq.pickup_zone or "").strip() or self.fallback_zone(rfq)
        if not zone_code:
            return
        if not rfq.pickup_zone:
            log.warning("pickup_zone_guessed", extra={"rfq": rfq.mail_id, "zone": zone_code})
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
        self._answered.setdefault(rfq_id, set()).add(mail.sender.strip().lower())
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
        hours = pickup_hours(mail.body)
        self._hours[(rfq_id, price.trucker)] = hours
        self._prices.setdefault(rfq_id, []).append(price)
        self._first_price_at.setdefault(rfq_id, time.monotonic())
        self.remember(price, rfq_id, hours)
        log.info("trucker_offer_stored", extra={"rfq": rfq_id, "mail": mail.id})

    def all_answered(self, rfq_id: int) -> bool:
        asked = self._asked.get(rfq_id, set())
        return bool(asked) and asked <= self._answered.get(rfq_id, set())

    def remember(self, price: PickupPrice, rfq_id: int, hours: float | None = None) -> None:
        if self.history_path is None:
            return
        zone = self.directory.zone(price.zone)
        row = {
            "zone": price.zone,
            "airport": zone.airport if zone else None,
            "trucker": price.trucker,
            "total": str(price.total),
            "currency": price.currency,
            "rfq": rfq_id,
            "hours": hours,
            "ts": time.time(),
        }
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with self.history_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
        except OSError as error:
            log.warning("pickup_history_write_failed", extra={"error": type(error).__name__})

    async def backfill(self, client: httpx.AsyncClient, base_url: str) -> int:
        if self.history_path is None or self.history():
            return 0
        rows, since = [], 0
        for _ in range(50):
            r = await client.get(
                f"{base_url}/v1/mailbox/messages", params={"since_id": since, "limit": 200}
            )
            if r.status_code != 200:
                break
            data = r.json()
            mails = data.get("messages", [])
            for m in mails:
                contact = self.directory.by_email(str(m.get("from", "")))
                subject = str(m.get("subject", ""))
                zone = re.search(r"zone (\d{2})", subject)
                ref = re.search(r"pickup request (\d+)", subject, re.I)
                if contact is None or contact.kind != "trucker" or not zone:
                    continue
                parsed = parse_price(str(m.get("body", "")))
                if parsed is None:
                    continue
                z = self.directory.zone(zone.group(1))
                rows.append(
                    {
                        "zone": zone.group(1),
                        "airport": z.airport if z else None,
                        "trucker": contact.name,
                        "total": str(parsed[0]),
                        "currency": parsed[1],
                        "hours": pickup_hours(str(m.get("body", ""))),
                        "rfq": int(ref.group(1)) if ref else None,
                        "ts": time.time(),
                    }
                )
            next_id = int(data.get("next_since_id") or since)
            if not mails or next_id <= since:
                break
            since = next_id
        if rows:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with self.history_path.open("a", encoding="utf-8") as fh:
                fh.writelines(json.dumps(row) + "\n" for row in rows)
        log.info("pickup_history_backfilled", extra={"rows": len(rows)})
        return len(rows)

    def history(self) -> list[dict]:
        if self.history_path is None or not self.history_path.exists():
            return []
        out = []
        for line in self.history_path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def estimate(self, rfq: RFQ) -> PickupPrice | None:
        zone_code = (rfq.pickup_zone or "").strip() or self.fallback_zone(rfq)
        rows = [
            r
            for r in self.history()
            if r.get("currency") == "EUR" and (r.get("hours") or 0) <= MAX_PICKUP_HOURS
        ]
        same_zone = [Decimal(r["total"]) for r in rows if r.get("zone") == zone_code]
        same_airport = [Decimal(r["total"]) for r in rows if r.get("airport") == rfq.origin]
        pool = same_zone or same_airport
        if not pool:
            return None
        cheapest = min(pool)
        return PickupPrice(
            source="estimate",
            trucker="estimate from earlier offers",
            zone=zone_code or "",
            total=cheapest,
            currency="EUR",
            received_at=self.now(),
        )

    async def collect(self, rfq: RFQ) -> PickupPrice | None:
        prices = self._prices.get(rfq.mail_id)
        if not prices:
            return None
        waited = time.monotonic() - self._first_price_at.get(rfq.mail_id, 0.0)
        since_rfq = (self.now() - rfq.received_at).total_seconds()
        if not self.all_answered(rfq.mail_id) and (
            waited < PICKUP_GRACE_S or since_rfq < PICKUP_WAIT_S
        ):
            return None
        fast = [
            p
            for p in prices
            if (getattr(self, "_hours", {}).get((rfq.mail_id, p.trucker)) or 0) <= MAX_PICKUP_HOURS
        ]
        if fast and len(fast) < len(prices):
            log.info(
                "slow_pickups_skipped",
                extra={"rfq": rfq.mail_id, "kept": len(fast), "of": len(prices)},
            )
        return min(fast or prices, key=lambda p: (p.currency != "EUR", p.total))
