"""Portal client + booking against a fake portal (httpx.MockTransport)."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import httpx

from sourcing.bids import Carrier
from sourcing.booking import book_option, parse_booking_confirmation
from sourcing.models import Shipment
from sourcing.portal import PortalClient, get_portal_options

NOW = datetime(2026, 11, 21, 16, 0, tzinfo=timezone.utc)


class FakePortal:
    """Prices FRA-JFK for airline PL: 2.50/kg below 1000 kg, 2.20/kg from 1000 kg."""

    def __init__(self):
        self.calls: list[str] = []
        self.rate_n = 0
        self.fail_rates_429 = 0
        self.book_status: list[int] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        assert request.headers["X-API-Key"] == "test-key"
        if path == "/v1/portal/ports":
            return httpx.Response(200, json={"lanes": [
                {"origin": "FRA", "destination": "JFK", "airlines": [{"code": "PL", "name": "Polaris Air Logistics"}]}]})
        if path == "/v1/portal/brackets":
            return httpx.Response(200, json={"airline": "Polaris Air Logistics", "airline_code": "PL",
                                             "breaks_kg": [0, 45, 100, 300, 500, 1000]})
        if path == "/v1/portal/rates":
            if self.fail_rates_429:
                self.fail_rates_429 -= 1
                return httpx.Response(429, headers={"Retry-After": "0"}, json={"detail": "slow down"})
            p = request.url.params
            w = D(p["weight_kg"])
            cw = max(w, D(p["volume_cbm"]) * 167)
            rate = D("2.20") if cw >= 1000 else D("2.50")
            self.rate_n += 1
            return httpx.Response(200, headers={"X-RateLimit-Limit": "30", "X-RateLimit-Remaining": "29"}, json={
                "rate_id": f"R-test{self.rate_n:08d}", "airline": "Polaris Air Logistics", "airline_code": "PL",
                "origin": "FRA", "destination": "JFK", "weight_kg": str(w), "chargeable_weight_kg": str(cw),
                "total": f"{cw * rate:.2f}", "currency": "EUR", "fx_eur_per_usd": None, "transit_days": 2,
                "valid_until": (NOW + timedelta(minutes=15)).isoformat(), "dataset_version": "v1"})
        if path == "/v1/portal/bookings":
            body = json.loads(request.content)
            status = self.book_status.pop(0) if self.book_status else 201
            if status in (200, 201):
                return httpx.Response(status, json={
                    "booking_reference": "BK-ABCD1234", "team_reference": body["team_reference"],
                    "rate_id": body["rate_id"], "airline": "Polaris Air Logistics", "airline_code": "PL",
                    "price": "2200.00", "currency": "EUR", "status": "booked"})
            return httpx.Response(status, json={"detail": f"status {status}"})
        return httpx.Response(404, json={"detail": "nope"})


def client(fake: FakePortal) -> PortalClient:
    http = httpx.AsyncClient(base_url="https://portal.test", transport=httpx.MockTransport(fake.handler))
    return PortalClient(api_key="test-key", http=http)


S = Shipment(rfq_id="RFQ-1", origin="FRA", destination="JFK", gross_weight=995,
             pieces=[{"count": 1, "length": 100, "width": 100, "height": 100}])


def test_portal_asks_next_break_and_keeps_cheaper():
    fake = FakePortal()

    async def run():
        async with client(fake) as portal:
            return await get_portal_options(S, portal)

    opts, notes = asyncio.run(run())
    assert len(opts) == 1
    o = opts[0]
    # 995 kg x 2.50 = 2487.50  vs  1000 kg x 2.20 = 2200.00
    assert o.total == D("2200.00") and o.billed_weight_kg == D("1000")
    assert o.rate_query["weight_kg"] == "1000" and "next break" in o.notes[0]
    assert fake.calls.count("GET /v1/portal/rates") == 2


def test_portal_waits_out_429():
    fake = FakePortal()
    fake.fail_rates_429 = 1

    async def run():
        async with client(fake) as portal:
            r = await portal.rate("FRA", "JFK", "PL", 50)
            return r, portal.rate_remaining

    r, remaining = asyncio.run(run())
    assert r.total == D("125.00") and remaining == 29


def test_booking_refreshes_expired_rate_id():
    fake = FakePortal()
    fake.book_status = [410, 201]

    async def run():
        async with client(fake) as portal:
            opts, _ = await get_portal_options(S, portal)
            return await book_option(opts[0], "RFQ-1", portal, S, now=NOW)

    res = asyncio.run(run())
    assert res.status == "booked" and res.booking_reference == "BK-ABCD1234"
    assert any("RateExpired" in n for n in res.notes)


def test_booking_old_rate_gets_fresh_one_first():
    fake = FakePortal()

    async def run():
        async with client(fake) as portal:
            opts, _ = await get_portal_options(S, portal)
            later = NOW + timedelta(minutes=20)  # rate_id is past valid_until
            return await book_option(opts[0], "RFQ-1", portal, S, now=later), fake.rate_n

    res, n_rates = asyncio.run(run())
    assert res.status == "booked" and n_rates == 3  # 2 for quoting + 1 fresh


def test_booking_portal_down_falls_back_to_email():
    fake = FakePortal()
    fake.book_status = [503]
    pl = Carrier("Polaris Air Logistics", "polaris-air-logistics@hackloop.mail", "airline", "PL")

    async def run():
        async with client(fake) as portal:
            opts, _ = await get_portal_options(S, portal)
            return await book_option(opts[0], "RFQ-1", portal, S, carriers=[pl], now=NOW)

    res = asyncio.run(run())
    assert res.status == "email" and res.email["to"] == pl.email
    assert "[BOOK RFQ-1]" in res.email["subject"]


def test_confirmation_mail():
    assert parse_booking_confirmation("Booking BK-1A2B3C4D confirmed") == "BK-1A2B3C4D"
    assert parse_booking_confirmation("Re: your quote", "nothing here") is None
