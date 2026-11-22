"""New monthly tariffs from airlines -> data/tariffs.json, automatically.

Airlines mail new price lists (truckers don't). The router hands us the mail
and its attachments; we parse each file with the parser for that format,
check it, and store it as a new version. The newest valid version per
airline wins (see tariffs.TariffStore.active). Anything we can't parse
raises an alarm instead of silently pricing from an old sheet.

Parsers live in kit_parsers.py and register themselves with @register.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from .bids import Carrier
from .models import Tariff
from .tariffs import TariffStore

Detect = Callable[[str, bytes, "str | None"], bool]
Parse = Callable[[str, bytes, "str | None"], list[Tariff]]
_PARSERS: list[tuple[str, Detect, Parse]] = []


class UnknownFormat(Exception):
    pass


def register(name: str, detect: Detect):
    """@register("pl-xlsx", lambda fn, data, code: fn.endswith(".xlsx") and code == "PL")"""

    def deco(fn: Parse) -> Parse:
        _PARSERS.append((name, detect, fn))
        return fn

    return deco


def parsers() -> list[str]:
    return [name for name, _, _ in _PARSERS]


def parse_tariff_file(filename: str, content: bytes, airline_code: str | None = None) -> list[Tariff]:
    for name, detect, parse in _PARSERS:
        try:
            ok = detect(filename, content, airline_code)
        except Exception:
            ok = False
        if ok:
            tariffs = parse(filename, content, airline_code)
            for t in tariffs:
                t.source_file = t.source_file or filename
                if f"parser:{name}" not in t.notes:
                    t.notes.append(f"parser:{name}")
            return tariffs
    raise UnknownFormat(f"no parser recognises {filename!r} (airline {airline_code or '?'})")


def validate_tariff(t: Tariff) -> list[str]:
    """Problems that should stop a tariff from going live."""
    p: list[str] = []
    if not re.fullmatch(r"[A-Z]{3}", t.currency or ""):
        p.append(f"currency {t.currency!r} is not a 3-letter code")
    if not t.lanes:
        p.append("no lanes")
    if t.valid_from and t.valid_to and t.valid_from > t.valid_to:
        p.append("valid_from is after valid_to")
    for lane in t.lanes:
        where = f"{lane.origin}-{lane.destination}"
        if not (len(lane.destination) == 3 and lane.destination.isalpha()):
            p.append(f"{where}: destination is not an IATA code")
        if not lane.breaks:
            p.append(f"{where}: no weight breaks")
            continue
        kg = [b.from_kg for b in lane.breaks]
        if kg != sorted(kg) or len(set(kg)) != len(kg):
            p.append(f"{where}: breaks not strictly ascending {kg}")
        if any(b.rate_per_kg <= 0 for b in lane.breaks):
            p.append(f"{where}: rate <= 0")
        if lane.min_charge < 0:
            p.append(f"{where}: negative minimum charge")
    for sc in t.surcharges:
        if sc.amount < 0:
            p.append(f"surcharge {sc.code} is negative")
    return p


@dataclass
class IngestResult:
    stored: list[str] = field(default_factory=list)  # tariff_ids now in the store
    notes: list[str] = field(default_factory=list)  # for the decision log
    alarms: list[str] = field(default_factory=list)  # show red in the UI


TARIFF_EXT = (".xlsx", ".xls", ".csv", ".pdf", ".txt", ".json")


def sender_of(message: dict) -> str:
    raw = message.get("from") or message.get("sender") or message.get("from_address") or ""
    if isinstance(raw, dict):
        raw = raw.get("address") or raw.get("email") or ""
    m = re.search(r"[\w.+-]+@[\w.-]+", str(raw))
    return m.group(0).lower() if m else str(raw).lower()


def carrier_by_email(email: str, carriers: list[Carrier]) -> Carrier | None:
    email = email.lower()
    return next((c for c in carriers if c.email.lower() == email), None)


def is_tariff_mail(message: dict, carriers: list[Carrier]) -> bool:
    """Airline sender + a sheet attachment (+ tariff words helps but isn't required)."""
    c = carrier_by_email(sender_of(message), carriers)
    if c is None or c.kind != "airline":
        return False
    names = [str(a.get("filename", "")).lower() for a in message.get("attachments") or []]
    return any(n.endswith(TARIFF_EXT) for n in names)


def ingest_tariff_mail(
    message: dict,
    files: list[tuple[str, bytes]],
    carriers: list[Carrier],
    store: TariffStore,
    today: date | None = None,
) -> IngestResult:
    """files = [(filename, content)] already downloaded from the mailbox."""
    res = IngestResult()
    carrier = carrier_by_email(sender_of(message), carriers)
    code = carrier.airline_code if carrier else None
    for filename, content in files:
        try:
            tariffs = parse_tariff_file(filename, content, code)
        except UnknownFormat as e:
            res.alarms.append(f"new tariff from {sender_of(message)} not parsed: {e}")
            continue
        except Exception as e:  # unreadable rows, or a parser blew up on a new layout
            detail = "; ".join(getattr(e, "problems", [])[:3])
            res.alarms.append(f"tariff {filename} not loaded: {e}" + (f" ({detail})" if detail else ""))
            continue
        for t in tariffs:
            if code and t.airline_code.upper() != code.upper():
                res.alarms.append(
                    f"{filename}: sheet says airline {t.airline_code}, sender is {code}"
                )
                continue
            problems = validate_tariff(t)
            if problems:
                res.alarms.append(f"{t.tariff_id} rejected: " + "; ".join(problems))
                continue
            res.notes += store.upsert(t)
            res.stored.append(t.tariff_id)
            if t.valid_to and today and t.valid_to < today:
                res.alarms.append(f"{t.tariff_id} is already expired ({t.valid_to})")
    return res
