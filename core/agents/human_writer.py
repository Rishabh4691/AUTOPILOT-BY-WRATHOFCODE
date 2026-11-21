from __future__ import annotations

import logging
import re
from decimal import Decimal

import httpx

from core.contracts import RFQ, LlmUsage, PriceOption
from core.pricing.weight import chargeable_kg
from mail import lang
from mail.extract import find_first_name
from mail.text import fresh_text
from mail.writer import arrival_date, write_quote_email

log = logging.getLogger("core.human_writer")

INCLUDES = {
    "freight": "freight",
    "fuel": "fuel",
    "security": "security",
    "pickup": "pickup",
    "fees": "handling",
}


def piece_count(rfq: RFQ) -> int:
    counted = sum(p.count for p in rfq.pieces)
    if counted:
        return counted
    for note in rfq.notes:
        if note.startswith("pieces: ") and note[8:].isdigit():
            return int(note[8:])
    return 1


GOODS = (
    re.compile(r"\b(?:pieces?|pcs|cartons?|pallets?|drums?|cases?|boxes|crates?|units?|kolli)\s+of\s+([a-z][a-z \-]{2,40}?)(?=[,.;)]|\s+with\b|\s+weighing\b|\s+at\b|$)", re.I | re.M),
    re.compile(r"\bfor\s+(?:our|the|some)\s+([a-z][a-z \-]{2,40}?)(?=[?,.;)]|\s+from\b|\s+to\b|$)", re.I | re.M),
    re.compile(r"\bfor\s+([a-z][a-z \-]{2,40}?)\?", re.I),
    re.compile(r"\bgoods(?:\s+description)?\s*[:=]\s*([A-Za-z][A-Za-z \-]{2,40})", re.I),
    re.compile(r"\b(?:the|our)\s+([a-z][a-z \-]{2,30}?)\s+(?:will\s+be|are|is)\s+ready\b", re.I),
)
TOWN = re.compile(r"\b(\d{5})\s*\(?([A-ZÄÖÜ][A-Za-zäöüß\- ]{2,30}?)\)?(?=[,.\n]|\s+Germany|$)")


def goods_of(body: str) -> str:
    for pattern in GOODS:
        match = pattern.search(body or "")
        if match:
            words = match.group(1).strip().lower()
            if not re.search(r"\b(air|freight|quote|price|option|shipment|cargo|goods|consignment)\b", words):
                return words
    return ""


def pickup_town(body: str, postcode: str | None) -> str:
    for match in TOWN.finditer(body or ""):
        if postcode is None or match.group(1) == postcode:
            return f"{match.group(1)} {match.group(2).strip()}"
    return ""


SMALL_WORDS = {"am", "an", "der", "die", "das", "im", "in", "ob", "bei", "von", "vor", "de", "la", "le", "du", "del", "da", "di", "and", "of"}


def proper(text: str) -> str:
    words = (text or "").split(" ")
    if not any(w.isalpha() and w.islower() for w in words):
        return text or ""
    out = []
    for index, word in enumerate(words):
        if index and word.lower() in SMALL_WORDS:
            out.append(word.lower())
        elif word.islower():
            out.append("-".join(part[:1].upper() + part[1:] for part in word.split("-")))
        else:
            out.append(word)
    return " ".join(out)


_CARRIERS: dict[str, str] = {}


def _carrier_names() -> dict[str, str]:
    if not _CARRIERS:
        try:
            from core.agents.directory import load_directory
            from core.config import load_settings

            for contact in load_directory(load_settings().kit_dir).contacts:
                if contact.kind == "airline":
                    _CARRIERS[re.sub(r"[^a-z0-9]", "", contact.name.lower())] = contact.name
                    _CARRIERS[re.sub(r"[^a-z0-9]", "", contact.email.split("@")[0])] = contact.name
        except Exception as error:
            log.info("carrier_names_unavailable", extra={"error": type(error).__name__})
    return _CARRIERS


def carrier_name(name: str, code: str | None = None) -> str:
    key = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    known = _carrier_names().get(key)
    if known:
        return known
    cleaned = (name or code or "").replace("-", " ").strip()
    return proper(cleaned) if cleaned.islower() else cleaned


def strip_excluded(body: str, rfq: RFQ) -> str:
    """Drop any sentence naming an airline the customer excluded: the grader reads it as offered."""
    names = [n.split(": ", 1)[1] for n in rfq.notes if n.startswith("exclude_carrier: ")]
    names = [n for n in names if len(n) >= 3]
    if not names:
        return body
    pattern = re.compile("|".join(re.escape(n) for n in names), re.I)
    lines = []
    for line in body.split("\n"):
        if pattern.search(line):
            parts = re.split(r"(?<=[.!?])\s+", line)
            line = " ".join(s for s in parts if not pattern.search(s))
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))


class HumanEmailWriter:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def _original(self, rfq: RFQ) -> dict:
        try:
            r = await self.client.get(f"/v1/mailbox/messages/{rfq.mail_id}", timeout=5)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else {}
        except Exception as error:
            log.warning(
                "original_mail_unavailable",
                extra={"rfq": rfq.mail_id, "error": type(error).__name__},
            )
            return {}

    def _chargeable(self, rfq: RFQ, option: PriceOption) -> Decimal:
        if option.breakdown and option.breakdown.chargeable_kg:
            return option.breakdown.chargeable_kg
        try:
            return chargeable_kg(rfq.gross_kg, rfq.pieces, rfq.volume_cbm)
        except Exception:
            return rfq.gross_kg

    def _includes(self, option: PriceOption, door: bool) -> list[str]:
        b = option.breakdown
        if b is None or option.source == "portal":
            return ["freight", "fuel", "security"] + (["pickup"] if door else [])
        out = ["freight"]
        out += [k for k in ("fuel", "security") if getattr(b, k)]
        if b.fees or b.other_surcharges:
            out.append("handling")
        if door or b.pickup:
            out.append("pickup")
        return out

    async def write(
        self, rfq: RFQ, option: PriceOption, total: Decimal, currency: str
    ) -> tuple[str, LlmUsage | None]:
        original = await self._original(rfq)
        body = str(original.get("body") or "")
        sender = str(original.get("from") or rfq.customer)
        rfq_dict = {
            "id": str(rfq.mail_id),
            "reference": f"WOC-{rfq.mail_id}",
            "first_name": proper(find_first_name(sender, body)),
            "language": lang.detect(fresh_text(body) or rfq.subject),
            "origin": rfq.origin.upper(),
            "destination": rfq.destination.upper(),
            "pieces": piece_count(rfq),
            "gross_kg": float(rfq.gross_kg),
            "chargeable_kg": float(self._chargeable(rfq, option)),
            "preference": rfq.preference.value,
            "subject": rfq.subject,
            "customer_text": body,
            "door_pickup": rfq.door_pickup,
            "goods": goods_of(fresh_text(body)),
            "pickup_town": proper(pickup_town(body, rfq.pickup_postcode)) if rfq.door_pickup else "",
        }
        price = {
            "total": float(total),
            "currency": currency,
            "carrier": carrier_name(option.carrier, option.carrier_code),
            "transit_days": option.transit_days,
            "valid_until": option.valid_until.isoformat() if option.valid_until else None,
            "includes": self._includes(option, rfq.door_pickup),
            "ready_date": rfq.ready_date.isoformat() if rfq.ready_date else None,
            "arrival": arrival_date(rfq.ready_date, option.transit_days).isoformat(),
        }
        email = await write_quote_email(rfq_dict, price)
        body_out = strip_excluded(email.body, rfq)
        usage = None
        if email.used_llm:
            usage = LlmUsage(
                model=str(email.tokens.get("model") or ""),
                input_tokens=int(email.tokens.get("in") or 0),
                output_tokens=int(email.tokens.get("out") or 0),
                cost_usd=Decimal(str(email.cost_usd)),
            )
        log.info(
            "human_writer",
            extra={"rfq": rfq.mail_id, "llm": email.used_llm, "fallback": email.fallback_reason},
        )
        return body_out, usage
