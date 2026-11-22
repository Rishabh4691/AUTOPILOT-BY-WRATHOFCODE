"""Portal prices we have seen, kept on disk, used when the rate portal is down.

Rounds 93-97 (22 Nov, from about 00:15 UTC): /v1/portal/rates answered 503 "The rate API is
unavailable", the rate desk and the airlines did not answer by mail, so every team quoted from the
PDF rate sheets. On the lanes asked for, the fast airlines are portal-only (DUS-MEX: Xenon, Tamarind,
Ultraviolet; DUS-JFK: Fjordline, Ultraviolet), so every quote was rejected too_low; the few teams
accepted (round 95: one team, factor 10) had portal prices from before the outage.

A portal total is (rate per kg + fuel per kg + security per kg) x chargeable kg once the minimum
charge no longer applies, so within one weight break the all-in price per kg is constant. One seen
price for (lane, airline, break) therefore prices any other weight in that break exactly. Nothing
is guessed across breaks: no observation in the right break means no estimate.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

log = logging.getLogger("sourcing.portal_cache")

CENT = Decimal("0.01")
# Weight breaks seen in the airline tariffs and on the portal. Without an airline's own breaks two
# weights count as one break only when no known break lies between them (conservative).
KNOWN_BREAKS = (Decimal(45), Decimal(100), Decimal(250), Decimal(300), Decimal(500), Decimal(1000), Decimal(2000))
# Below this the minimum charge may apply, so price per kg is not constant: never estimate there.
MIN_RELIABLE_KG = Decimal(100)
_lock = threading.Lock()


def cache_path() -> Path:
    return Path(os.environ.get("PORTAL_CACHE_PATH", "data/portal_cache.jsonl"))


@dataclass(frozen=True)
class Seen:
    origin: str
    destination: str
    airline: str
    code: str | None
    chargeable_kg: Decimal
    total: Decimal
    currency: str
    transit_days: int
    seen_at: str
    breaks: tuple[Decimal, ...] = ()

    @property
    def per_kg(self) -> Decimal:
        return self.total / self.chargeable_kg


def record(origin: str, destination: str, airline: str, code: str | None, chargeable_kg, total,
           currency: str, transit_days: int, breaks=(), path: Path | None = None) -> None:
    """Remember one portal price (called for every portal answer while the portal works)."""
    try:
        row = {
            "origin": origin.upper(), "destination": destination.upper(), "airline": airline, "code": code,
            "chargeable_kg": str(chargeable_kg), "total": str(total), "currency": currency,
            "transit_days": int(transit_days), "seen_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "breaks": [str(b) for b in breaks or ()],
        }
        target = path or cache_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with _lock, target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:  # never let the cache break a quote
        log.warning("portal_cache_write_failed", exc_info=True)


def load(path: Path | None = None) -> list[Seen]:
    target = path or cache_path()
    out: list[Seen] = []
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            r = json.loads(line)
            seen = Seen(r["origin"], r["destination"], r["airline"], r.get("code"),
                        Decimal(r["chargeable_kg"]), Decimal(r["total"]), r.get("currency", "EUR"),
                        int(r["transit_days"]), r.get("seen_at", ""),
                        tuple(Decimal(b) for b in r.get("breaks") or ()))
        except (ValueError, KeyError, InvalidOperation, TypeError):
            continue
        if seen.chargeable_kg > 0 and seen.total > 0:
            out.append(seen)
    return out


def same_break(a: Decimal, b: Decimal, breaks: tuple[Decimal, ...] = ()) -> bool:
    edges = breaks or KNOWN_BREAKS
    return not any(min(a, b) < edge <= max(a, b) for edge in edges)


def estimate(origin: str, destination: str, chargeable_kg: Decimal, seen: list[Seen] | None = None,
             path: Path | None = None) -> list[dict]:
    """One estimated portal price per airline on the lane, from a price seen in the same break.

    Also tries the next break up (the portal keeps the cheaper of own weight and next break)."""
    rows = seen if seen is not None else load(path)
    lane = [s for s in rows if s.origin == origin.upper() and s.destination == destination.upper()]
    out = []
    for airline in sorted({s.airline for s in lane}):
        mine = [s for s in lane if s.airline == airline and s.chargeable_kg >= MIN_RELIABLE_KG]
        if not mine:
            continue
        breaks = next((s.breaks for s in reversed(mine) if s.breaks), ())
        candidates = []
        same = [s for s in mine if same_break(s.chargeable_kg, chargeable_kg, breaks)]
        if same and chargeable_kg >= MIN_RELIABLE_KG:
            s = same[-1]  # newest
            candidates.append((s.per_kg * chargeable_kg, s, "same break"))
        higher = sorted({e for e in (breaks or KNOWN_BREAKS) if e > chargeable_kg})
        if higher:
            nxt = higher[0]
            up = [s for s in mine if s.chargeable_kg >= nxt and same_break(s.chargeable_kg, nxt, breaks)]
            if up:
                s = up[-1]
                candidates.append((s.per_kg * nxt, s, f"next break {nxt} kg"))
        if not candidates:
            continue
        total, s, how = min(candidates, key=lambda c: c[0])
        out.append({
            "airline": airline, "code": s.code, "total": total.quantize(CENT, rounding=ROUND_HALF_UP),
            "currency": s.currency, "transit_days": s.transit_days, "chargeable_kg": chargeable_kg,
            "basis": f"{how}: {s.total} for {s.chargeable_kg} kg seen {s.seen_at}",
        })
    return out
