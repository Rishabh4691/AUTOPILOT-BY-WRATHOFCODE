"""Cargo insurance the customer asks us to include in the all-in price.

Round 91: "Please include cargo insurance in the all-in price, on the terms of our frame
agreement: goods value 22000 EUR, insured at 110 % of that value, premium rate 0.40 %."
Premium = goods value x insured share x premium rate = 22000 x 1.10 x 0.0040 = 96.80 EUR.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ASKED = re.compile(
    r"\b(?:includ\w*|add|with|plus|cover)\b[^.\n]{0,60}\b(?:cargo |transport )?insurance\b|"
    r"\binsurance\b[^.\n]{0,40}\b(?:includ\w*|in the (?:all-in )?price)|"
    r"versicherung\w*[^.\n]{0,40}(?:einschlie\w*|inklusive|enthalten|mitversichern)|"
    r"(?:einschlie\w*|inklusive|inkl\.?|mit)\s+[^.\n]{0,30}versicherung",
    re.I,
)
NUMBER = r"(\d[\d.,' ]*\d|\d)"
VALUE = re.compile(
    r"(?:goods|cargo|commercial|invoice|shipment|declared|insured|waren|sendungs)?\s*"
    r"(?:value|wert|warenwert)\w*\s*(?:of|von|:|=|is|ist|at)?\s*(?:EUR|€)?\s*" + NUMBER + r"\s*(?:EUR|€|euros?)?",
    re.I,
)
SHARE = re.compile(
    r"(?:insured (?:at|for)|versichert (?:zu|mit)|zu)\s*" + NUMBER + r"\s*%|" + NUMBER + r"\s*%\s*(?:of (?:that|the|its|this) (?:goods |cargo )?value|des (?:waren)?werts)",
    re.I,
)
RATE = re.compile(
    r"(?:premium|insurance)?\s*(?:rate|prämie\w*|praemie\w*|satz)\s*(?:of|von|:|=|is|ist|at)?\s*" + NUMBER + r"\s*%|"
    + NUMBER + r"\s*%\s*(?:premium|prämie|praemie)",
    re.I,
)


def _num(text: str) -> Decimal | None:
    raw = text.replace("'", "").replace(" ", "")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".") if raw.rfind(",") > raw.rfind(".") else raw.replace(",", "")
    elif "," in raw:
        head, tail = raw.rsplit(",", 1)
        raw = raw.replace(",", ".") if len(tail) != 3 else raw.replace(",", "")
    elif raw.count(".") == 1 and len(raw.rsplit(".", 1)[1]) == 3 and len(raw) > 5:
        raw = raw.replace(".", "")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _first(pattern: re.Pattern[str], text: str) -> Decimal | None:
    m = pattern.search(text)
    if not m:
        return None
    group = next((g for g in m.groups() if g), None)
    return _num(group) if group else None


def premium(text: str) -> Decimal | None:
    """The insurance premium in the goods-value currency, or None when none is asked for."""
    if not text or not ASKED.search(text):
        return None
    value = _first(VALUE, text)
    rate = _first(RATE, text)
    if value is None or rate is None or value <= 0 or rate <= 0:
        return None
    share = _first(SHARE, text) or Decimal("100")
    amount = value * share / Decimal(100) * rate / Decimal(100)
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def note_value(notes: tuple[str, ...] | list[str]) -> Decimal | None:
    for note in notes:
        if note.startswith("insurance_premium: "):
            try:
                return Decimal(note.split(": ", 1)[1])
            except InvalidOperation:
                return None
    return None
