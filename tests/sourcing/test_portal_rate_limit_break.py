"""Round 150 (one_of_two): a rate-limited next-break probe must be retried, not skipped."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from sourcing import portal as portal_mod
from sourcing.portal import PortalClient, get_portal_options

BASE = "https://portal.test"


def rate(weight: str, total: str) -> dict:
    return {
        "rate_id": f"R-FQ-{weight}",
        "airline": "Fjordline Air Cargo",
        "airline_code": "FQ",
        "origin": "FRA",
        "destination": "TLV",
        "weight_kg": weight,
        "chargeable_weight_kg": weight,
        "total": total,
        "currency": "EUR",
        "transit_days": 2,
        "valid_until": "2026-11-22T07:30:00+00:00",
        "dataset_version": "test",
    }


@respx.mock(assert_all_called=False)
async def test_rate_limited_next_break_is_waited_out(respx_mock: respx.MockRouter, monkeypatch) -> None:
    slept: list[float] = []

    async def no_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(portal_mod.asyncio, "sleep", no_sleep)
    respx_mock.get(f"{BASE}/v1/portal/ports").respond(
        json={"lanes": [{"origin": "FRA", "destination": "TLV",
                         "airlines": [{"code": "FQ", "name": "Fjordline Air Cargo"}]}]}
    )
    respx_mock.get(f"{BASE}/v1/portal/brackets").respond(
        json={"airline": "Fjordline Air Cargo", "airline_code": "FQ", "breaks_kg": [0, 45, 100, 250, 500, 1000, 2000]}
    )
    calls = {"1000": 0}

    def priced(request: httpx.Request) -> httpx.Response:
        weight = request.url.params["weight_kg"]
        if weight.startswith("1000"):
            calls["1000"] += 1
            if calls["1000"] == 1:
                return httpx.Response(429, headers={"Retry-After": "44"}, json={"detail": "limit"})
            return httpx.Response(200, json=rate("1000", "2970.00"))
        return httpx.Response(200, json=rate("951", "3138.30"))

    respx_mock.get(f"{BASE}/v1/portal/rates").mock(side_effect=priced)
    client = PortalClient(api_key="k", base_url=BASE)
    try:
        options, notes = await get_portal_options(
            {"rfq_id": "446592", "origin": "FRA", "destination": "TLV", "gross_weight": "951", "volume_cbm": "4.67"},
            client,
        )
    finally:
        await client.aclose()
    assert len(options) == 1 and options[0].total == Decimal("2970.00"), notes
    assert calls["1000"] == 2 and any(s >= 44 for s in slept)
    assert any("waiting 44s" in n for n in notes)


def test_retry_after_is_read_from_the_error() -> None:
    err = portal_mod.RateLimited("rate limit on /v1/portal/rates, retry after 44s", 429, "")
    assert portal_mod.retry_after_s(err) == pytest.approx(44.0)
