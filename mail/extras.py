"""Extra charges the customer asks us to include in the all-in price (tax, duty, fees, ...).

Round 91 asked for cargo insurance; new kinds of add-on keep coming, so anything beyond the fixed
insurance rule is read by the model, then recomputed here from the numbers it reports. Runs only
when the customer's mail itself contains an amount or a percentage.
"""

from __future__ import annotations

import json
import logging
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

log = logging.getLogger("mail.extras")

MONEY_OR_PERCENT = re.compile(
    r"\d\s*%|%\s*\d|(?:EUR|USD|CHF|GBP|€|\$)\s*\d|\d[\d.,]*\s*(?:EUR|USD|CHF|GBP|€|euros?)\b", re.I
)
PROMPT = """A customer asks an air freight forwarder for an all-in price. Read their mail and list every
EXTRA charge they explicitly ask us to ADD to or INCLUDE in the all-in price, beyond air freight,
fuel, security and truck pickup. Examples: insurance, a tax, a duty, a handling or documentation fee,
a surcharge. Ignore amounts that only describe the goods (weight, volume, goods value on its own) and
anything they say they do NOT want. {skip}
For each extra give exactly one of:
- "fixed_eur": a fixed amount in EUR, computed from the numbers in the mail (e.g. value x share x rate),
- "percent_of_total": a percentage of our freight + pickup price.
Reply with JSON only: {{"extras": [{{"label": "short name", "fixed_eur": number or null,
"percent_of_total": number or null, "formula": "how you computed it"}}]}}. If there are none, reply
{{"extras": []}}.

Mail:
---
{mail}
---"""


def worth_asking(text: str) -> bool:
    return bool(text and MONEY_OR_PERCENT.search(text))


def _dec(value) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return None
    return d if d > 0 else None


async def read_extras(text: str, skip_insurance: bool) -> list[dict]:
    """[{label, fixed_eur: Decimal|None, percent_of_total: Decimal|None}], empty on any doubt."""
    if not worth_asking(text):
        return []
    from mail import gateway

    skip = "Insurance is already handled; do not list it." if skip_insurance else ""
    try:
        reply = await gateway.chat(
            [{"role": "user", "content": PROMPT.format(mail=text[:4000], skip=skip)}],
            max_tokens=400,
            model="gpt-4.1-mini",
        )
        raw = reply.text.strip().strip("`")
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
        items = json.loads(raw).get("extras") or []
    except Exception as error:
        log.warning("extras_unavailable", extra={"error": type(error).__name__})
        return []
    out = []
    for item in items[:5]:
        fixed, pct = _dec(item.get("fixed_eur")), _dec(item.get("percent_of_total"))
        if fixed is None and pct is None:
            continue
        if pct is not None and pct > 50:
            continue
        label = re.sub(r"[^A-Za-z0-9 \-]", "", str(item.get("label") or "extra charge"))[:40].strip().lower()
        out.append({"label": label or "extra charge", "fixed_eur": fixed, "percent_of_total": pct})
    return out


def notes_for(extras: list[dict]) -> list[str]:
    notes = []
    for e in extras:
        if e["fixed_eur"] is not None:
            notes.append(f"extra_fixed: {e['fixed_eur']}|{e['label']}")
        else:
            notes.append(f"extra_percent: {e['percent_of_total']}|{e['label']}")
    return notes


def apply(total: Decimal, notes) -> tuple[Decimal, list[str]]:
    """Total with every extra from the notes added, and the labels for the email."""
    labels: list[str] = []
    base = total
    for note in notes:
        kind, _, rest = note.partition(": ")
        if kind not in ("extra_fixed", "extra_percent"):
            continue
        amount_text, _, label = rest.partition("|")
        try:
            amount = Decimal(amount_text)
        except InvalidOperation:
            continue
        if kind == "extra_fixed":
            total += amount
        else:
            total += (base * amount / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        labels.append(label or "extra charge")
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), labels
