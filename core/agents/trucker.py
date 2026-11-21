from __future__ import annotations

import asyncio
import json
import os
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


TOTAL_WORDS = re.compile(
    r"all[- ]?in|total|gesamt|insgesamt|pauschal|fixed price|festpreis", re.IGNORECASE
)
TOTAL_WINDOW = 120


def parse_price(text: str) -> tuple[Decimal, str] | None:
    """The all-in price of a trucker reply.

    Prefers the amount closest after an "all-in" / "total" word, so a reply that lists
    a base rate and surcharges before the total is read as the total. Otherwise the
    first amount.
    """
    text = re.sub(r"(\d),-", r"\1", text or "")  # "95,- EUR"
    found: list[tuple[int, Decimal, str]] = []
    for pos, amount_text, currency in _candidates(text):
        amount = parse_amount(amount_text)
        if amount is not None and amount > 0:
            found.append((pos, amount, currency))
    if not found:
        return None
    keyed: list[tuple[int, int, Decimal, str]] = []
    for pos, amount, currency in found:
        before = [m.end() for m in TOTAL_WORDS.finditer(text, 0, pos)]
        if before and pos - before[-1] <= TOTAL_WINDOW:
            keyed.append((pos - before[-1], pos, amount, currency))
    if keyed:
        _, _, amount, currency = min(keyed)
        return amount, currency
    _, amount, currency = found[0]
    return amount, currency


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


# Truckers refuse a request without a 5-digit postcode ("We do not serve this lane/zone:
# pickup postcode 93", rounds 2 and 15). When the customer gave none, use the town centre.
ZONE_POSTCODES = {
    "20": "20095", "21": "21335", "22": "22297", "24": "24103", "28": "28195",
    "35": "35390", "36": "36037", "40": "40213", "41": "41061", "42": "42103",
    "44": "44135", "45": "45127", "47": "47051", "50": "50667", "51": "51465",
    "53": "53111", "55": "55116", "60": "60311", "61": "61348", "63": "63065",
    "64": "64283", "65": "65183", "70": "70173", "71": "71032", "72": "72070",
    "73": "73728", "80": "80331", "81": "81369", "84": "84028", "85": "85049",
    "86": "86150", "93": "93047",
}


def full_postcode(rfq: RFQ, zone: str) -> str:
    postcode = pickup_postcode(rfq)
    if postcode and re.fullmatch(r"\d{5}", postcode) and postcode.startswith(zone):
        return postcode
    return ZONE_POSTCODES.get(zone, f"{zone}000")


def request_body(rfq: RFQ, zone: str, area: str, airport: str) -> str:
    ready = rfq.ready_date.isoformat() if rfq.ready_date else "as soon as possible"
    postcode = full_postcode(rfq, zone)
    return "\n".join(
        [
            "Hello,",
            "",
            f"Please quote a pickup from postcode {postcode} {area}, Germany (zone {zone}) "
            f"to {airport} airport.",
            f"Pickup postcode: {postcode}.",
            *shipment_lines(rfq),
            f"Ready date: {ready}.",
            f"Please reply with your all-in price and pickup time, and keep "
            f"'Pickup request {rfq.mail_id}' in the subject.",
            "",
            "Best regards,",
            "WRATHOFCODE Air Freight",
        ]
    )


REFUSAL = re.compile(
    r"do not serve|don't serve|not serve this|to quote we need|we need the|please send (?:us )?the",
    re.IGNORECASE,
)


def followup_body(rfq: RFQ, zone: str, area: str, airport: str) -> str:
    ready = rfq.ready_date.isoformat() if rfq.ready_date else "as soon as possible"
    details = " ".join(shipment_lines(rfq))
    return "\n".join(
        [
            "Hello,",
            "",
            f"thank you. The pickup address is postcode {full_postcode(rfq, zone)} {area}, "
            f"Germany (zone {zone}), delivery to {airport} airport.",
            f"{details} Ready date: {ready}.",
            "",
            "Please send your all-in price and pickup time.",
            "",
            "Best regards",
            "WRATHOFCODE Air Freight",
        ]
    )


PICKUP_TIME = re.compile(
    r"\b(?:pickup|pick-up|collection|abholung|transit|lead)\s*time\s*(?:is|of|:|=)?\s*(?:about|approx\.?|ca\.?)?\s*(\d+(?:[.,]\d+)?)\s*(hours?|hrs?|h|days?|d|stunden|tage?)\b",
    re.I,
)
MAX_PICKUP_HOURS = Decimal("24")  # proven from board accuracy points: rounds 4, 13, 18; see tests/core/test_trucking_fixes.py
PRICE_WEIGHT = Decimal("0.5")
TIME_WEIGHT = Decimal("0.5")


MORE_PICKUP_TIMES = (
    # "Pickup within 30 hours", "within 1 day"
    re.compile(r"\bwithin\s+(\d+(?:[.,]\d+)?)\s*(hours?|hrs?|h|days?|tage?n?)\b", re.I),
    # "Abholzeit: 6 Stunden", "Abholung in 1 Tag"
    re.compile(
        r"\babhol(?:zeit|ung)\s*(?:in|:|=)?\s*(?:ca\.?\s*)?(\d+(?:[.,]\d+)?)\s*(stunden?|std\.?|h|tage?n?|tag)\b",
        re.I,
    ),
    # "pickup takes 25 hours" (round 42), "collection will take 1 day", "pickup is possible in 8 hours"
    re.compile(
        r"\b(?:pick[- ]?up|collection)\s+(?:takes|will\s+take|needs|is\s+possible\s+in|is\s+in|within)\s+"
        r"(?:about\s+|approx\.?\s+|ca\.?\s+)?(\d+(?:[.,]\d+)?)\s*(hours?|hrs?|h|days?)\b",
        re.I,
    ),
    # "pickup in 18h", "collect in 2 days"
    re.compile(
        r"\b(?:pick[- ]?up|collect(?:ion)?)\s+in\s+(\d+(?:[.,]\d+)?)\s*(hours?|hrs?|h|days?)\b", re.I
    ),
)
NEXT_DAY = re.compile(r"\bnext[- ]day\b|\btomorrow\b|\bmorgen\b|\bam nächsten tag\b", re.I)


def _hours(value: str, unit: str) -> Decimal:
    number = Decimal(value.replace(",", "."))
    unit = unit.lower()
    return number * 24 if unit.startswith(("day", "d", "tag")) and not unit.startswith("dh") else number


def parse_hours(text: str) -> Decimal | None:
    text = text or ""
    match = PICKUP_TIME.search(text)
    if match:
        return _hours(match.group(1), match.group(2))
    for pattern in MORE_PICKUP_TIMES:
        found = pattern.search(text)
        if found:
            return _hours(found.group(1), found.group(2))
    if NEXT_DAY.search(text):
        return Decimal(24)
    # Last resort: the only "N hours" in a trucker reply is its pickup time. A missing time let
    # a 25 h offer ("pickup takes 25 hours") pass the 24 h rule in round 42.
    plain = re.findall(r"\b(\d+(?:[.,]\d+)?)\s*(hours?|hrs?|stunden)\b", text, re.I)
    if len({v for v, _ in plain}) == 1:
        return _hours(plain[0][0], plain[0][1])
    return None


def pickup_rule() -> str:
    return (os.getenv("PICKUP_RULE") or "fast_cheapest").strip().lower()


def in_eur(price: PickupPrice) -> PickupPrice | None:
    """The offer in EUR, or None when we have no rate for its currency."""
    if price.currency == "EUR":
        return price
    from sourcing import fx

    rate = fx.get_rate(price.currency)
    if rate is None:
        log.info("trucker_offer_no_fx", extra={"currency": price.currency, "trucker": price.trucker})
        return None
    total = (price.total * rate).quantize(Decimal("0.01"))
    return price.model_copy(update={"total": total, "currency": "EUR"})


def best_offer(prices: list[PickupPrice], preference: str = "cheapest") -> PickupPrice:
    # A CHF or USD offer is compared in EUR instead of being ignored.
    pool = [p for p in (in_eur(x) for x in prices) if p is not None] or prices
    if preference == "fastest":
        timed = [p for p in pool if p.pickup_hours is not None]
        if timed:
            return min(timed, key=lambda p: (p.pickup_hours, p.total))
    if pickup_rule() == "fast_cheapest":
        # An offer that does not state its pickup time is kept, not silently dropped.
        quick = [p for p in pool if p.pickup_hours is None or p.pickup_hours <= MAX_PICKUP_HOURS]
        return min(quick or pool, key=lambda p: p.total)
    if pickup_rule() != "balanced":
        return min(pool, key=lambda p: p.total)
    timed = [p for p in pool if p.pickup_hours is not None and p.pickup_hours > 0]
    if not timed:
        return min(pool, key=lambda p: p.total)
    cheapest = min(p.total for p in timed)
    fastest = min(p.pickup_hours for p in timed if p.pickup_hours is not None)
    return min(
        timed,
        key=lambda p: (
            PRICE_WEIGHT * p.total / cheapest + TIME_WEIGHT * (p.pickup_hours or fastest) / fastest,
            p.total,
        ),
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
        self._answered: dict[int, set[str]] = {}
        self._first_price_at: dict[int, float] = {}
        self._zones: dict[int, str] = {}
        self._sent_ids: dict[int, int] = {}
        self._prices: dict[int, list[PickupPrice]] = {}
        self._rfqs: dict[int, RFQ] = {}
        self._reasked: dict[int, set[str]] = {}
        self._tasks: set[asyncio.Task[None]] = set()

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
        self._rfqs[rfq.mail_id] = rfq
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

    def _ask_again(self, rfq_id: int, mail: Mail) -> bool:
        """Answer "we do not serve" / "to quote we need ..." once, with every detail.

        Truckers refuse a request that lacks a full postcode or the volume (rounds 1, 2
        and 15). One follow-up in the same thread gets the price within about 30 s.
        """
        sender = mail.sender.strip().lower()
        rfq = self._rfqs.get(rfq_id)
        if rfq is None or sender in self._reasked.setdefault(rfq_id, set()):
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        zone_code = self._zones[rfq_id]
        zone = self.directory.zone(zone_code)
        airport = zone.airport if zone else rfq.origin
        area = zone.area if zone else f"zone {zone_code}"
        subject = mail.subject if mail.subject.lower().startswith("re:") else f"Re: {mail.subject}"
        body = followup_body(rfq, zone_code, area, airport)
        self._reasked[rfq_id].add(sender)
        task = loop.create_task(self._send(rfq_id, sender, subject, body))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        log.info("trucker_asked_again", extra={"rfq": rfq_id, "trucker": sender})
        return True

    def offer(self, mail: Mail) -> None:
        rfq_id = self._rfq_for(mail)
        if rfq_id is None:
            return
        parsed = parse_price(mail.body) or parse_price(SUBJECT_REF.sub(" ", mail.subject))
        if parsed is None and REFUSAL.search(mail.body or "") and self._ask_again(rfq_id, mail):
            return  # still waiting for this trucker's real answer
        self._answered.setdefault(rfq_id, set()).add(mail.sender.strip().lower())
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
                pickup_hours=parse_hours(mail.body),
            )
        except ValidationError:
            log.info("trucker_offer_invalid", extra={"rfq": rfq_id, "mail": mail.id})
            return
        self._prices.setdefault(rfq_id, []).append(price)
        self._first_price_at.setdefault(rfq_id, time.monotonic())
        self.remember(price, rfq_id)
        log.info("trucker_offer_stored", extra={"rfq": rfq_id, "mail": mail.id})

    def all_answered(self, rfq_id: int) -> bool:
        asked = self._asked.get(rfq_id, set())
        return bool(asked) and asked <= self._answered.get(rfq_id, set())

    def remember(self, price: PickupPrice, rfq_id: int) -> None:
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
            "kg": str(self._rfqs[rfq_id].gross_kg) if rfq_id in self._rfqs else None,
            "hours": None if price.pickup_hours is None else str(price.pickup_hours),
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
                        "rfq": int(ref.group(1)) if ref else None,
                        "hours": (lambda h: None if h is None else str(h))(
                            parse_hours(str(m.get("body", "")))
                        ),
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
        """Best guess when no trucker answered in time.

        One guess per trucker that served this zone before: its price at the closest
        weight, scaled by the square root of the weight ratio, with its pickup time.
        Then the same rule as for real offers picks one. (The old version took the lowest
        price ever seen in the zone, whatever the weight: -46 % to +57 % off.)
        """
        zone_code = (rfq.pickup_zone or "").strip() or self.fallback_zone(rfq)
        rows = [r for r in self.history() if r.get("currency") == "EUR"]
        pool = [r for r in rows if r.get("zone") == zone_code] or [
            r for r in rows if r.get("airport") == rfq.origin
        ]
        if not pool:
            return None
        weight = Decimal(str(rfq.gross_kg)) if rfq.gross_kg else None
        guesses: list[PickupPrice] = []
        for trucker in sorted({str(r.get("trucker")) for r in pool}):
            own = [r for r in pool if str(r.get("trucker")) == trucker]
            weighed = [r for r in own if r.get("kg")]
            if weight and weighed:
                near = min(weighed, key=lambda r: abs(Decimal(r["kg"]) - weight))
                # Trucker prices have a fixed base, so they grow slower than the weight:
                # square-root scaling fits rounds 1 to 26 best (22 % mean error vs 47 % before).
                total = Decimal(near["total"]) * (weight / Decimal(near["kg"])).sqrt()
            else:
                near = own[-1]
                total = Decimal(near["total"])
            hours = near.get("hours")
            guesses.append(
                PickupPrice(
                    source="estimate",
                    trucker=f"estimate ({trucker})",
                    zone=zone_code or "",
                    total=total.quantize(Decimal("0.01")),
                    currency="EUR",
                    received_at=self.now(),
                    pickup_hours=None if hours in (None, "None") else Decimal(str(hours)),
                )
            )
        preference = getattr(rfq, "preference", "cheapest")
        return best_offer(guesses, str(getattr(preference, "value", preference)))

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
        preference = getattr(rfq, "preference", "cheapest")
        return best_offer(prices, str(getattr(preference, "value", preference)))
