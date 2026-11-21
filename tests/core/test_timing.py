from datetime import UTC, datetime, timedelta

import pytest

from core.timing import TimingPolicy, decide, is_stale, seconds_since

POLICY = TimingPolicy()
NONE: frozenset[str] = frozenset()
PENDING = frozenset({"portal"})


def test_hard_stop_sends_when_ready() -> None:
    assert decide(POLICY, 320, PENDING, True, True, False, False) == "send"


def test_hard_stop_holds_without_option() -> None:
    assert decide(POLICY, 320, NONE, False, False, False, False) == "hold"


def test_hard_stop_holds_without_needed_pickup() -> None:
    assert decide(POLICY, 320, NONE, True, False, True, False) == "hold"


def test_waits_without_option() -> None:
    assert decide(POLICY, 250, NONE, False, False, False, False) == "wait"


def test_waits_for_needed_pickup() -> None:
    assert decide(POLICY, 250, NONE, True, False, True, False) == "wait"


def test_sends_after_wait_until_even_if_pending_can_win() -> None:
    assert decide(POLICY, 240, PENDING, True, True, False, False) == "send"


def test_sends_after_send_at_when_pending_cannot_win() -> None:
    assert decide(POLICY, 130, PENDING, True, False, False, False) == "send"


def test_waits_after_send_at_when_pending_can_win() -> None:
    assert decide(POLICY, 130, PENDING, True, True, True, True) == "wait"


def test_sends_early_when_everything_is_in() -> None:
    assert decide(POLICY, 5, NONE, True, False, True, True) == "send"


def test_waits_early_with_pending_sources() -> None:
    assert decide(POLICY, 5, PENDING, True, False, False, False) == "wait"


def test_seconds_since_and_stale() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert seconds_since(now - timedelta(seconds=30), now) == 30
    assert not is_stale(now - timedelta(seconds=359), now)
    assert is_stale(now - timedelta(seconds=360), now)
    assert is_stale(now - timedelta(seconds=100), now, lifetime_s=60)


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        now = datetime.now(UTC)
        seconds_since(now.replace(tzinfo=None), now)
