"""Carrier bids by email (no LLM: every gateway call costs points).

At t = 0 of an RFQ, send one bid request to each airline that serves the
destination (2-5 of them) and, for door-to-port, to the truckers for the
pickup zone. Replies come back in the same thread; we match them with
`in_reply_to` / `references` and read the price with regexes.

    tracker = BidTracker()
    for c in carriers_for(shipment, carriers):
        ref = bid_ref(shipment.rfq_id, c)
        mail = bid_request_email(shipment, c, ref)
        sent = await mailbox.send(**mail)          # Aditi's mailbox client
        tracker.record_sent(sent, shipment.rfq_id, c, ref)
    ...
    hit = tracker.match(incoming_mail)              # when a mail arrives
    if hit:
        quote = parse_bid_reply(incoming_mail["body"])
        option = bid_option(shipment, hit, quote)  # PriceOption or None
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from . import fx
from .models import PriceOption, Shipment
from .weights import (
    chargeable_weight_kg,
    gross_weight_kg,
    money,
    to_cm,
    total_volume_cbm,
)

TEAM_SIGNATURE = "WRATHOFCODE"


@dataclass
class Carrier:
    name: str
    email: str
    kind: Literal["airline", "trucker", "ratedesk"]
    airline_code: str | None = None
    destinations: list[str] = field(default_factory=list)  # IATA; empty = any
    zones: list[str] = field(default_factory=list)  # pickup zones (truckers)


def carriers_for(s: Shipment, carriers: list[Carrier]) -> list[Carrier]:
    """Airlines serving the destination + truckers for the pickup zone (door pickup)."""
    dest = s.destination.upper()
    chosen = [
        c
        for c in carriers
        if c.kind == "airline" and (not c.destinations or dest in [d.upper() for d in c.destinations])
    ]
    if s.door_pickup:
        zone = (s.pickup_zone or "").upper()
        chosen += [
            c
            for c in carriers
            if c.kind == "trucker" and (not c.zones or zone in [z.upper() for z in c.zones])
        ]
    return chosen


def bid_ref(rfq_id: str, carrier: Carrier) -> str:
    tag = carrier.airline_code or re.sub(r"[^A-Za-z0-9]", "", carrier.name)[:8] or "C"
    return f"{rfq_id}-{tag}".upper()


def _pieces_text(s: Shipment) -> str:
    rows = []
    for p in s.pieces:
        l, w, h = (to_cm(x, p.dim_unit) for x in (p.length, p.width, p.height))
        rows.append(f"{p.count} x {l:.0f} x {w:.0f} x {h:.0f} cm")
    return "; ".join(rows) if rows else "see volume"


def bid_request_email(s: Shipment, carrier: Carrier, ref: str) -> dict:
    """{'to', 'subject', 'body'} for POST /v1/mailbox/messages. Plain template."""
    gross = gross_weight_kg(s)
    cbm = total_volume_cbm(s)
    cw = chargeable_weight_kg(s)
    goods = "Lithium batteries UN3480 (cargo aircraft only)" if s.lithium_un3480 else "General cargo"
    ready = s.ready_date.isoformat() if s.ready_date else "as soon as possible"
    if carrier.kind == "trucker":
        subject = f"[BID {ref}] Pickup quote request to {s.origin} airport"
        lines = [
            f"Hello {carrier.name},",
            "",
            "please quote a pickup from the shipper's door to the airport cargo terminal.",
            "",
            f"Reference: {ref}",
            f"Pickup: zone {s.pickup_zone or '-'}"
            + (f", postcode {s.pickup_postcode}" if s.pickup_postcode else ""),
            f"Deliver to: {s.origin} airport, cargo terminal",
            f"Pieces: {_pieces_text(s)}",
            f"Gross weight: {gross:.1f} kg, volume {cbm:.3f} m3",
            f"Ready: {ready}",
            "",
            "Please reply in this thread with your price and currency.",
        ]
    else:
        subject = f"[BID {ref}] Air freight quote request {s.origin}-{s.destination}"
        lines = [
            f"Hello {carrier.name} team,",
            "",
            "please quote air freight for this shipment:",
            "",
            f"Reference: {ref}",
            f"Route: {s.origin} -> {s.destination} (airport to airport)",
            f"Pieces: {_pieces_text(s)}",
            f"Gross weight: {gross:.1f} kg",
            f"Volume: {cbm:.3f} m3",
            f"Chargeable weight: {cw:.1f} kg",
            f"Goods: {goods}",
            f"Ready: {ready}",
            "",
            "Please reply in this thread with:",
            "- the all-in price and currency (freight and all surcharges)",
            "- the transit time in days",
            "- how long the offer is valid",
        ]
    lines += ["", "Thank you,", TEAM_SIGNATURE]
    return {"to": carrier.email, "subject": subject, "body": "\n".join(lines)}


# ------------------------------------------------------------------ parsing
_CUR = r"(EUR|USD|CHF|GBP|€|\$|£)"
_NUM = r"(\d{1,3}(?:[ '’.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_SYMBOL = {"€": "EUR", "$": "USD", "£": "GBP"}
_PER_KG = re.compile(r"^\s*(?:/|per)\s*kg", re.I)
_TOTAL_WORDS = re.compile(r"\b(total|all[- ]?in|grand total|in total|overall)\b", re.I)
_PRICE_WORDS = re.compile(r"\b(price|rate|offer|quote|quotation|amount|cost|charge)\b", re.I)
_DECLINE = re.compile(
    r"\b(cannot|can't|can not|unable to|no capacity|not able to|decline|regret)\b", re.I
)
_RANGE_DAYS = re.compile(
    r"(\d+)\s*(?:-|–|to)\s*(\d+)\s*(?:calendar |working |business )?days?", re.I
)
_DAYS = re.compile(r"(\d+)\s*(?:calendar |working |business )?(?:days?|d)\b", re.I)
_HOURS = re.compile(r"(\d+)\s*(?:hours|hrs|h)\b", re.I)
_VALID = re.compile(r"valid(?:ity)?\s*(?:until|till|through|to|:)?\s*([^\n;]{3,40})", re.I)


def parse_amount(text: str) -> Decimal | None:
    """'1,234.50' '1.234,50' "1'234.50" '1 234,5' '980' -> Decimal."""
    t = text.strip().replace(" ", "").replace("'", "").replace("’", "")
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        head, _, tail = t.rpartition(",")
        t = t.replace(",", "") if len(tail) == 3 else head.replace(",", "") + "." + tail
    elif t.count(".") > 1 or (t.count(".") == 1 and len(t.rpartition(".")[2]) == 3):
        t = t.replace(".", "")  # 1.234 or 1.234.567 -> thousands
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


@dataclass
class Money:
    amount: Decimal
    currency: str
    per_kg: bool
    line: str


def find_money(text: str) -> list[Money]:
    found: list[Money] = []
    patterns = (
        re.compile(_CUR + r"\s*" + _NUM),  # EUR 1,234.50 / € 980
        re.compile(_NUM + r"\s*" + _CUR),  # 1.234,50 EUR
    )
    for line in text.splitlines():
        spans = []
        for pi, pat in enumerate(patterns):
            for m in pat.finditer(line):
                if any(a < m.end() and m.start() < b for a, b in spans):
                    continue
                cur, num = (m.group(1), m.group(2)) if pi == 0 else (m.group(2), m.group(1))
                amount = parse_amount(num)
                if amount is None:
                    continue
                spans.append((m.start(), m.end()))
                per_kg = bool(_PER_KG.match(line[m.end():]))
                found.append(Money(amount, _SYMBOL.get(cur, cur.upper()), per_kg, line.strip()))
    return found


@dataclass
class BidQuote:
    total: Decimal | None = None
    currency: str | None = None
    per_kg: Decimal | None = None
    transit_days: int | None = None
    valid_text: str | None = None
    declined: bool = False
    confidence: Literal["high", "low", "none"] = "none"
    evidence: list[str] = field(default_factory=list)  # lines we read, for the trace


def _strip_quoted(body: str) -> str:
    """Drop our own quoted request (lines starting with '>' or after 'On ... wrote:')."""
    out = []
    for line in body.splitlines():
        if line.lstrip().startswith(">") or re.match(r"^\s*On .+wrote:\s*$", line):
            break
        out.append(line)
    return "\n".join(out)


def parse_bid_reply(body: str) -> BidQuote:
    text = _strip_quoted(body or "")
    q = BidQuote()
    monies = find_money(text)
    totals = [m for m in monies if not m.per_kg and _TOTAL_WORDS.search(m.line)]
    prices = [m for m in monies if not m.per_kg]
    per_kg = [m for m in monies if m.per_kg]

    if totals:
        pick, q.confidence = totals[-1], "high"
    elif len(prices) == 1:
        pick, q.confidence = prices[0], "high"
    elif prices:
        worded = [m for m in prices if _PRICE_WORDS.search(m.line)]
        pool = worded or prices
        pick, q.confidence = max(pool, key=lambda m: m.amount), "low"
    else:
        pick = None
    if pick:
        q.total, q.currency = pick.amount, pick.currency
        q.evidence.append(pick.line)
    if per_kg:
        q.per_kg = per_kg[0].amount
        q.currency = q.currency or per_kg[0].currency
        q.evidence.append(per_kg[0].line)
        if q.total is None:
            q.confidence = "low"

    if m := _RANGE_DAYS.search(text):
        q.transit_days = max(int(m.group(1)), int(m.group(2)))
    elif m := _DAYS.search(text):
        q.transit_days = int(m.group(1))
    elif m := _HOURS.search(text):
        q.transit_days = max(1, -(-int(m.group(1)) // 24))
    if m := _VALID.search(text):
        q.valid_text = m.group(1).strip()
    if q.total is None and q.per_kg is None and _DECLINE.search(text):
        q.declined = True
    return q


# ----------------------------------------------------------------- tracking
@dataclass
class SentBid:
    message_id: int
    rfq_id: str
    carrier: Carrier
    ref: str
    sent_at: datetime
    replied: bool = False


class BidTracker:
    """Remembers which bid request went to whom, and matches replies to them."""

    def __init__(self) -> None:
        self._by_id: dict[int, SentBid] = {}
        self._by_ref: dict[str, SentBid] = {}

    def record_sent(self, sent_message: dict, rfq_id: str, carrier: Carrier, ref: str) -> SentBid:
        sb = SentBid(int(sent_message["id"]), rfq_id, carrier, ref, datetime.now(UTC))
        self._by_id[sb.message_id] = sb
        self._by_ref[ref.upper()] = sb
        return sb

    def match(self, message: dict) -> SentBid | None:
        ids = [message.get("in_reply_to"), *reversed(message.get("references") or [])]
        for i in ids:
            if i is not None and int(i) in self._by_id:
                return self._mark(self._by_id[int(i)])
        if m := re.search(r"\[BID ([A-Z0-9_-]+)\]", message.get("subject") or "", re.I):
            if sb := self._by_ref.get(m.group(1).upper()):
                return self._mark(sb)
        return None

    @staticmethod
    def _mark(sb: SentBid) -> SentBid:
        sb.replied = True
        return sb

    def for_rfq(self, rfq_id: str) -> list[SentBid]:
        return [sb for sb in self._by_id.values() if sb.rfq_id == rfq_id]

    def waiting(self, rfq_id: str) -> list[SentBid]:
        return [sb for sb in self.for_rfq(rfq_id) if not sb.replied]


def bid_option(s: Shipment, sent: SentBid, q: BidQuote) -> PriceOption | None:
    """Turn a parsed reply into a PriceOption (None if declined or no price)."""
    if q.declined:
        return None
    cw = chargeable_weight_kg(s)
    total = q.total
    notes = [f"bid reply ({q.confidence} confidence): " + " | ".join(q.evidence)]
    if total is None and q.per_kg is not None:
        total = money(q.per_kg * cw)
        notes.append(f"price given per kg: {q.per_kg} x {cw} kg")
    if total is None or q.currency is None:
        return None
    if q.valid_text:
        notes.append(f"valid {q.valid_text}")
    c = sent.carrier
    return PriceOption(
        source="bid",
        leg="pickup" if c.kind == "trucker" else "air",
        airline_code=c.airline_code,
        airline=c.name,
        carrier_email=c.email,
        origin=s.origin,
        destination=s.destination,
        chargeable_weight_kg=cw if c.kind != "trucker" else None,
        billed_weight_kg=cw if c.kind != "trucker" else None,
        total=money(total),
        currency=q.currency,
        total_eur=fx.to_eur(total, q.currency),
        transit_days=q.transit_days,
        fetched_at=datetime.now(UTC),
        notes=notes,
    )
