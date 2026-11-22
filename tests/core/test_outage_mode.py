"""Outage mode (rounds 93-100): retry the portal, add a learned premium, learn it from the board."""

from __future__ import annotations

from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from core.agents import outage


def board(rows):
    return [{"sent_at": at, "verdict": v, "reason": r} for at, v, r in rows]


def simulate(hidden_pct: float, rounds: int = 8) -> int | None:
    """Rounds until accepted when the grader expects price x (1 + hidden_pct %), +-5 % accepted."""
    state: dict = {}
    base = D("1000")
    history = []
    for n in range(rounds):
        state = outage.learn(state, board(history))
        pct = outage.current_pct(state, "fastest")
        at = f"2026-11-22T00:{10 + n:02d}:00"
        state = outage.record(state, "fastest", at, pct)
        quote = outage.apply(base, pct)
        expected = base * (1 + D(str(hidden_pct)) / 100)
        dev = (quote - expected) / expected
        if abs(dev) <= D("0.05"):
            return n + 1
        history.append((at, "rejected", "too_low" if dev < 0 else "too_high"))
    return None


@pytest.mark.parametrize("hidden", [3, 7, 12, 18, 25, 35])
def test_premium_is_found_within_a_few_outage_rounds(hidden: float) -> None:
    found = simulate(hidden)
    assert found is not None and found <= 4, found


def test_accepted_premium_is_kept() -> None:
    state = outage.record({}, "fastest", "2026-11-22T00:10:00", D(10))
    state = outage.learn(state, board([("2026-11-22T00:10:00", "accepted", None)]))
    assert outage.current_pct(state, "fastest") == D(10)


def test_preferences_learn_separately() -> None:
    state = outage.record({}, "fastest", "2026-11-22T00:10:00", D(10))
    state = outage.learn(state, board([("2026-11-22T00:10:00", "rejected", "too_low")]))
    assert outage.current_pct(state, "fastest") == D(20)
    assert outage.current_pct(state, "cheapest") == 0


def test_only_requests_that_hit_a_503_are_touched(monkeypatch) -> None:
    monkeypatch.setattr(outage, "_down", set())
    assert not outage.hit_outage(1)
    outage.mark_down(2)
    assert outage.hit_outage(2) and not outage.hit_outage(1)
    monkeypatch.setenv("OUTAGE_MODE", "0")
    assert not outage.hit_outage(2)


def test_state_survives_restart(tmp_path) -> None:
    path = tmp_path / "o.json"
    outage.save(outage.record({}, "fastest", "2026-11-22T00:10:00", D(10)), path)
    assert outage.load(path)["fastest"]["pending"][0]["pct"] == "10"
    assert outage.load(tmp_path / "missing.json") == {}


async def test_portal_is_retried_and_late_airlines_are_kept(monkeypatch) -> None:
    from core.agents import sourcing_adapter
    from tests.core.test_booking import SETTINGS  # noqa: F401  (settings shape)

    calls = []

    async def fake(shipment, portal):
        calls.append(1)
        if len(calls) == 1:
            return [], ["XC: portal unavailable: The rate API is unavailable."]
        option = SimpleNamespace(airline="Xenon Cargo Airlines")
        return [option], []

    monkeypatch.setattr(sourcing_adapter.sourcing, "get_portal_options", fake)
    monkeypatch.setattr(sourcing_adapter, "convert_all", lambda options, now, name: list(options))
    monkeypatch.setattr(outage, "_down", set())
    src = sourcing_adapter.SourcingPortalPriceSource.__new__(sourcing_adapter.SourcingPortalPriceSource)
    src.portal, src.now, src.last_notes = None, lambda: None, []
    rfq = SimpleNamespace(mail_id=93)
    monkeypatch.setattr(sourcing_adapter, "to_shipment", lambda r: None)
    got = await src.quote(rfq)
    assert [o.airline for o in got] == ["Xenon Cargo Airlines"] and len(calls) == 2
    assert outage.hit_outage(93)


async def test_fastest_quote_gets_the_premium_after_a_503(tmp_path, monkeypatch) -> None:
    from decimal import Decimal

    async def no_board(client, settings):
        return []

    monkeypatch.setattr(outage, "board_requests", no_board)
    from test_orchestrator import harness

    h = harness(tmp_path / "f")
    rfq = SimpleNamespace(mail_id=7, preference=SimpleNamespace(value="fastest"),
                          received_at=SimpleNamespace(isoformat=lambda: "2026-11-22T00:20:00"))
    assert await h.orchestrator.outage_premium(rfq, Decimal("250.50")) == Decimal("275.55")


async def test_quote_gets_the_premium_only_after_a_503(tmp_path, monkeypatch) -> None:
    from test_orchestrator import drain, harness, mail

    async def no_board(client, settings):
        return []

    monkeypatch.setattr(outage, "board_requests", no_board)
    monkeypatch.setattr(outage, "_down", set())
    normal = harness(tmp_path / "a")
    normal.mailbox.batches = [[mail(1)]]
    await normal.orchestrator.poll_once()
    await drain(normal)
    assert "250.50 EUR" in normal.mailbox.sent[0].body  # untouched

    outage.mark_down(2)
    hit = harness(tmp_path / "b")
    hit.mailbox.batches = [[mail(2)]]
    await hit.orchestrator.poll_once()
    await drain(hit)
    # the harness request is "cheapest": no premium until a cheapest outage quote comes back too_low
    assert "250.50 EUR" in hit.mailbox.sent[0].body
    assert outage.load()["cheapest"]["pending"][0]["pct"] == "0"
    state = outage.learn(outage.load(), board([(outage.load()["cheapest"]["pending"][0]["at"], "rejected", "too_low")]))
    assert outage.current_pct(state, "cheapest") == D(10)
