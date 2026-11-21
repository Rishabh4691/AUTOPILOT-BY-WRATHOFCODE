from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.contracts import Verdict

SEND_AT_S = 120
WAIT_UNTIL_S = 240
HARD_STOP_S = 315


@dataclass(frozen=True)
class TimingPolicy:
    send_at_s: float = SEND_AT_S
    wait_until_s: float = WAIT_UNTIL_S
    hard_stop_s: float = HARD_STOP_S


def decide(
    policy: TimingPolicy,
    elapsed_s: float,
    pending_sources: frozenset[str],
    have_option: bool,
    pending_can_win: bool,
    needs_pickup: bool,
    have_pickup: bool,
) -> Verdict:
    ready = have_option and (not needs_pickup or have_pickup)
    if elapsed_s >= policy.hard_stop_s:
        return "send" if ready else "hold"
    if not ready:
        return "wait"
    if elapsed_s >= policy.wait_until_s:
        return "send"
    if elapsed_s >= policy.send_at_s and (not pending_sources or not pending_can_win):
        return "send"
    if not pending_sources:
        return "send"
    return "wait"


def seconds_since(received_at: datetime, now: datetime) -> float:
    if received_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("timestamps must carry a timezone")
    return (now - received_at).total_seconds()


def is_stale(received_at: datetime, now: datetime, lifetime_s: float = 360) -> bool:
    return seconds_since(received_at, now) >= lifetime_s
