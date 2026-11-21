from __future__ import annotations

import logging
import re
from decimal import Decimal

from core.contracts import RFQ, PriceOption

log = logging.getLogger("core.limits")

FREIGHTER_ONLY_CM = Decimal("160")


def tallest(rfq: RFQ) -> Decimal | None:
    heights = [p.height_cm for p in rfq.pieces]
    for note in rfq.notes:
        if note.startswith("tallest_cm: "):
            try:
                heights.append(Decimal(note[12:]))
            except ArithmeticError:
                pass
    return max(heights) if heights else None


def lithium_alone(rfq: RFQ) -> bool:
    return "UN3480" in rfq.notes or bool(re.search(r"UN\s?3480", rfq.subject, re.I))


def _key(name: str) -> str:
    return re.sub(r"[^a-z]", "", (name or "").lower())


def airline_limits() -> dict[str, tuple[Decimal | None, bool | None]]:
    try:
        from sourcing.sheets import _store

        tariffs = _store().active(None)
    except Exception as error:
        log.warning("limits_unavailable", extra={"error": type(error).__name__})
        return {}
    out = {}
    for t in tariffs:
        out[_key(t.airline)] = (t.max_piece_height_cm, t.accepts_un3480)
    return out


def why_not(option: PriceOption, rfq: RFQ, limits: dict) -> str | None:
    max_h, takes_lithium = limits.get(_key(option.carrier), (None, None))
    h = tallest(rfq)
    if max_h is not None and h is not None and h > Decimal(max_h):
        return f"{option.carrier}: piece {h} cm is taller than its {max_h} cm limit"
    if takes_lithium is False and lithium_alone(rfq):
        return f"{option.carrier}: does not carry UN3480 lithium batteries"
    return None


def usable(options: list[PriceOption], rfq: RFQ) -> tuple[list[PriceOption], list[str]]:
    limits = airline_limits()
    keep, dropped = [], []
    for o in options:
        reason = why_not(o, rfq, limits)
        (dropped.append(reason) if reason else keep.append(o))
    return (keep or options), dropped
