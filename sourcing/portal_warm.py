"""Fill the portal price cache in the background while the portal works.

Rounds 93-97 were lost because the portal went down and we had no saved portal prices for the
lanes asked. The cache (sourcing/portal_cache.py) prices an outage exactly only when it holds a price
for the same lane, airline and weight break, so this walks every portal lane, airline and break
once, slowly, and keeps the result fresh.

Live quotes always come first: the warm-up never uses more than half of the per-minute rate limit,
waits whenever a live quote used the portal in the last 60 s, and stops for a minute on a 503 or
429. Every rate it reads is stored by PortalClient.rate() itself (portal_cache.record).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sourcing import portal_cache

log = logging.getLogger("sourcing.portal_warm")

DEFAULT_WEIGHTS = (Decimal(100), Decimal(300), Decimal(500), Decimal(1000), Decimal(2000))
FRESH = timedelta(hours=6)
LIVE_QUIET_S = 60.0
_last_live = 0.0


def mark_live() -> None:
    """Called by the live quote path; the warm-up stays out of the way for a minute."""
    global _last_live
    _last_live = time.monotonic()


def weights_for(breaks) -> list[Decimal]:
    """One weight per break from 100 kg up: the break itself is the first weight of that break."""
    edges = sorted(Decimal(str(b)) for b in breaks or ())
    picked = [b for b in edges if b >= portal_cache.MIN_RELIABLE_KG]
    return picked or list(DEFAULT_WEIGHTS)


def have(rows, origin: str, destination: str, airline: str, weight: Decimal, breaks, now: datetime) -> bool:
    for r in rows:
        if (r.origin, r.destination) != (origin, destination) or airline not in (r.code, r.airline):
            continue
        if not portal_cache.same_break(r.chargeable_kg, weight, tuple(Decimal(str(b)) for b in breaks or ())):
            continue
        try:
            if now - datetime.fromisoformat(r.seen_at) < FRESH:
                return True
        except ValueError:
            continue
    return False


async def plan(client) -> list[tuple[str, str, str, Decimal]]:
    lanes = await client.ports()
    rows = portal_cache.load()
    now = datetime.now(UTC)
    todo = []
    for lane in lanes:
        for airline in lane.airlines:
            try:
                breaks = await client.brackets(airline.code)  # not rate-limited
            except Exception:
                breaks = []
            for w in weights_for(breaks):
                if not have(rows, lane.origin.upper(), lane.destination.upper(), airline.code, w, breaks, now):
                    todo.append((lane.origin.upper(), lane.destination.upper(), airline.code, w))
    return todo


def room(client) -> bool:
    """Leave at least half of the per-minute portal budget to live quotes."""
    limit, left = getattr(client, "rate_limit", None), getattr(client, "rate_remaining", None)
    if limit is None or left is None:
        return True
    return left > limit / 2


async def warm_forever(client, stop: asyncio.Event, gap_s: float = 4.0, idle_s: float = 600.0) -> None:
    from sourcing.portal import PortalUnavailable, RateLimited

    while not stop.is_set():
        try:
            todo = await plan(client)
        except Exception as error:  # portal down or ports failing: try again later
            log.info("portal_warm_wait", extra={"error": type(error).__name__})
            await _sleep(stop, 60)
            continue
        log.info("portal_warm_plan", extra={"todo": len(todo)})
        done = 0
        for origin, destination, code, weight in todo:
            if stop.is_set():
                return
            while time.monotonic() - _last_live < LIVE_QUIET_S or not room(client):
                await _sleep(stop, 5)
                if stop.is_set():
                    return
            try:
                await client.rate(origin, destination, code, weight, 0)
                done += 1
            except (PortalUnavailable, RateLimited):
                await _sleep(stop, 60)
                break
            except Exception:
                pass  # lane or airline not priceable at this weight: skip it
            await _sleep(stop, gap_s)
        log.info("portal_warm_pass", extra={"read": done, "todo": len(todo)})
        await _sleep(stop, idle_s if done == len(todo) else 30)


async def _sleep(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass
