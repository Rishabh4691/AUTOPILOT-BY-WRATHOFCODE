from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

from core.agents.portal import PortalPriceSource, shipment_volume
from core.contracts import RFQ, Piece, Preference, SourceUnavailable
from tests.core.test_llm import SETTINGS

BASE = "https://portal.test"
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
PORTS = {
    "lanes": [
        {
            "origin": "FRA",
            "destination": "ORD",
            "airlines": [{"code": "IB", "name": "Ibisair Cargo"}, {"code": "VG", "name": "Vega"}],
        }
    ]
}


def rate(code: str, total: str = "1234.50", **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "rate_id": f"R-{code}",
        "airline": f"Airline {code}",
        "airline_code": code,
        "origin": "FRA",
        "destination": "ORD",
        "weight_kg": 300,
        "chargeable_weight_kg": "320.0",
        "total": total,
        "currency": "EUR",
        "transit_days": 2,
        "valid_until": "2026-01-01T13:00:00Z",
        "dataset_version": "v1",
    }
    body.update(extra)
    return body


def make_rfq(origin: str = "FRA") -> RFQ:
    return RFQ(
        mail_id=9,
        thread_root_id=9,
        customer="buyer@example.test",
        subject="Quote",
        origin=origin,
        destination="ORD",
        pieces=(
            Piece(count=2, length_cm=Decimal(100), width_cm=Decimal(80), height_cm=Decimal(60)),
        ),
        gross_kg=Decimal(300),
        door_pickup=False,
        preference=Preference.CHEAPEST,
        preference_assumed=False,
        received_at=NOW,
    )


def source(client: httpx.AsyncClient) -> PortalPriceSource:
    return PortalPriceSource(client, replace(SETTINGS, base_url=BASE), lambda: NOW)


def rate_route(mock: respx.MockRouter, code: str) -> respx.Route:
    return mock.get(f"{BASE}/v1/portal/rates", params={"airline": code})


def test_volume_from_pieces() -> None:
    assert shipment_volume(make_rfq()) == Decimal("0.960")


@respx.mock(assert_all_called=False)
async def test_quote_maps_rates_and_caches_ports(respx_mock: respx.MockRouter) -> None:
    ports = respx_mock.get(f"{BASE}/v1/portal/ports").respond(json=PORTS)
    rate_route(respx_mock, "IB").respond(json=rate("IB"))
    rate_route(respx_mock, "VG").respond(json=rate("VG", "999.99", surprise="x"))
    async with httpx.AsyncClient() as client:
        portal = source(client)
        options = await portal.quote(make_rfq())
        await portal.quote(make_rfq())
    assert ports.call_count == 1
    by_code = {o.carrier_code: o for o in options}
    assert by_code["IB"].total == Decimal("1234.50")
    assert by_code["VG"].rate_id == "R-VG"
    assert by_code["IB"].breakdown is not None
    assert by_code["IB"].breakdown.chargeable_kg == Decimal("320.0")
    assert by_code["IB"].rate_id_at == NOW and not by_code["IB"].includes_pickup
    request = rate_route(respx_mock, "IB").calls.last.request
    assert request.url.params["volume_cbm"] == "0.960"


@respx.mock(assert_all_called=False)
async def test_missing_lane(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE}/v1/portal/ports").respond(json=PORTS)
    async with httpx.AsyncClient() as client:
        with pytest.raises(SourceUnavailable, match="lane not on portal"):
            await source(client).quote(make_rfq("MUC"))


@respx.mock(assert_all_called=False)
async def test_429_then_success(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE}/v1/portal/ports").respond(json=PORTS)
    rate_route(respx_mock, "IB").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0.01"}),
            httpx.Response(200, json=rate("IB")),
        ]
    )
    rate_route(respx_mock, "VG").respond(404, json={"detail": "nope"})
    async with httpx.AsyncClient() as client:
        portal = source(client)
        options = await portal.quote(make_rfq())
    assert [o.carrier_code for o in options] == ["IB"]
    assert portal.last_errors == ["VG: status 404"]


@respx.mock(assert_all_called=False)
async def test_503_is_unavailable(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE}/v1/portal/ports").respond(503, json={"detail": "maintenance"})
    async with httpx.AsyncClient() as client:
        with pytest.raises(SourceUnavailable, match="maintenance"):
            await source(client).quote(make_rfq())


@respx.mock(assert_all_called=False)
async def test_malformed_rate_skipped_and_fx_kept(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE}/v1/portal/ports").respond(json=PORTS)
    broken = rate("IB")
    del broken["total"]
    rate_route(respx_mock, "IB").respond(json=broken)
    rate_route(respx_mock, "VG").respond(
        json=rate("VG", "1500.00", currency="USD", fx_eur_per_usd="0.92")
    )
    async with httpx.AsyncClient() as client:
        portal = source(client)
        options = await portal.quote(make_rfq())
    assert len(options) == 1
    assert options[0].currency == "USD"
    assert options[0].breakdown is not None
    assert options[0].breakdown.fx_note == "fx_eur_per_usd=0.92"
    assert portal.last_errors[0].startswith("IB: malformed rate")


@respx.mock(assert_all_called=False)
async def test_fresh_rate(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE}/v1/portal/ports").respond(json=PORTS)
    rate_route(respx_mock, "IB").respond(json=rate("IB", "1300.00"))
    rate_route(respx_mock, "VG").respond(json=rate("VG"))
    async with httpx.AsyncClient() as client:
        portal = source(client)
        old = (await portal.quote(make_rfq()))[0]
        fresh = await portal.fresh_rate(old, make_rfq())
    assert fresh.total == Decimal("1300.00")


@respx.mock(assert_all_called=False)
async def test_next_weight_break_is_used_when_cheaper(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(f"{BASE}/v1/portal/ports").respond(json=PORTS)
    respx_mock.get(f"{BASE}/v1/portal/brackets").respond(
        json={"airline": "x", "airline_code": "IB", "breaks_kg": [0, 45, 100, 300, 500, 1000, 2000]}
    )

    def priced(request: httpx.Request) -> httpx.Response:
        weight = request.url.params["weight_kg"]
        if request.url.params["airline"] != "IB":
            return httpx.Response(404)
        if weight == "500":
            return httpx.Response(200, json=rate("IB", "900.00", chargeable_weight_kg="500"))
        return httpx.Response(200, json=rate("IB", "1000.00", chargeable_weight_kg="320"))

    respx_mock.get(f"{BASE}/v1/portal/rates").mock(side_effect=priced)
    async with httpx.AsyncClient() as client:
        options = await source(client).quote(make_rfq())
    ib = [o for o in options if o.carrier_code == "IB"]
    assert len(ib) == 1 and ib[0].total == Decimal("900.00")
