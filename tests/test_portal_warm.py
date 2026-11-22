"""Background fill of the portal cache (rounds 93-97 follow-up)."""

import asyncio
from decimal import Decimal as D
from types import SimpleNamespace

from sourcing import portal_cache, portal_warm


class FakeClient:
    def __init__(self, fail_after: int | None = None) -> None:
        self.calls: list[tuple] = []
        self.rate_limit, self.rate_remaining = 60, 60
        self.fail_after = fail_after

    async def ports(self):
        airline = SimpleNamespace(code="XC", name="Xenon Cargo Airlines")
        return [SimpleNamespace(origin="DUS", destination="MEX", airlines=[airline])]

    async def brackets(self, code):
        return [45, 100, 300, 500, 1000]

    async def rate(self, origin, destination, code, weight, volume):
        from sourcing.portal import PortalUnavailable

        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise PortalUnavailable("The rate API is unavailable.", 503)
        self.calls.append((origin, destination, code, weight))
        portal_cache.record(origin, destination, "Xenon Cargo Airlines", code, weight, weight * D("2.5"), "EUR", 2,
                            breaks=[D(45), D(100), D(300), D(500), D(1000)])


def test_one_weight_per_break_from_100_kg() -> None:
    assert portal_warm.weights_for([45, 100, 300, 500, 1000]) == [D(100), D(300), D(500), D(1000)]
    assert portal_warm.weights_for([]) == list(portal_warm.DEFAULT_WEIGHTS)


async def test_warm_up_is_off_when_disabled(monkeypatch) -> None:
    from core.main import portal_warm_up

    monkeypatch.setenv("PORTAL_WARM", "0")
    await asyncio.wait_for(portal_warm_up(SimpleNamespace(api_key="k", base_url="http://x"), asyncio.Event()), 1)


async def test_warm_up_fills_every_break_then_an_outage_is_priced() -> None:
    client, stop = FakeClient(), asyncio.Event()
    portal_warm._last_live = 0.0
    task = asyncio.create_task(portal_warm.warm_forever(client, stop, gap_s=0, idle_s=60))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if len(client.calls) == 4:
            break
    stop.set()
    await task
    assert [c[3] for c in client.calls] == [D(100), D(300), D(500), D(1000)]
    [e] = portal_cache.estimate("DUS", "MEX", D("1136"))
    assert e["airline"] == "Xenon Cargo Airlines" and e["total"] == D("2840.00")
    # a second pass finds everything fresh and reads nothing
    assert await portal_warm.plan(client) == []


async def test_warm_up_steps_aside_for_live_quotes_and_low_budget() -> None:
    client = FakeClient()
    client.rate_limit, client.rate_remaining = 10, 7  # live quotes may need these reads
    assert not portal_warm.room(client)
    client.rate_remaining = 8
    assert portal_warm.room(client)


async def test_outage_stops_the_pass() -> None:
    client, stop = FakeClient(fail_after=1), asyncio.Event()
    portal_warm._last_live = 0.0
    task = asyncio.create_task(portal_warm.warm_forever(client, stop, gap_s=0, idle_s=60))
    await asyncio.sleep(0.1)
    stop.set()
    await task
    assert len(client.calls) == 1


def test_refresh_only_in_the_quiet_part_of_a_round(monkeypatch) -> None:
    monkeypatch.setattr(portal_warm, "_last_live", 1000.0)
    assert not portal_warm.in_quiet_window(1030.0)  # live quote still running
    assert portal_warm.in_quiet_window(1120.0)
    assert not portal_warm.in_quiet_window(1300.0)  # next round is about to start
