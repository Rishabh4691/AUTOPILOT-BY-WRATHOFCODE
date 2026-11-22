"""Rounds 103/104: accepted quotes stored with only the airline NAME (no code, airports or rate id).

The fresh portal rate was asked with the name, found nothing, and the airline got an empty
"Route:  to ." booking mail; it answered "we cannot find this rate" and nothing was booked.
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import respx

from core.agents.booking import BookingAgent
from core.agents.directory import load_directory
from core.contracts import RFQ, PriceOption, Preference
from core.store import Store
from tests.core.test_booking import BASE, KIT, Orch
from tests.core.test_llm import SETTINGS


class FakePortal:
    def __init__(self) -> None:
        self.asked: list[str] = []

    async def _ports_data(self, deadline):
        lane = SimpleNamespace(origin="STR", destination="LAX", airlines=[
            SimpleNamespace(code="PL", name="Polaris Air Logistics"),
            SimpleNamespace(code="JP", name="Juniper Cargo Lines")])
        return SimpleNamespace(lanes=[lane])

    async def rate_for(self, rfq, airline):
        self.asked.append(airline)
        if airline != "PL":  # the portal only knows codes
            return None
        return PriceOption(source="portal", carrier="Polaris Air Logistics", carrier_code="PL",
                           rate_id="R-FRESHrate0001", total=Decimal("4455.22"), currency="EUR", transit_days=5)


class Extractor:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def extract(self, mail):
        if self.fail:
            raise ValueError("cannot read")
        return RFQ(mail_id=mail.id, thread_root_id=mail.id, customer="c@x", subject="s", origin="STR",
                   destination="LAX", pieces=(), gross_kg=Decimal("1841"), volume_cbm=Decimal("4.63"),
                   door_pickup=False, preference=Preference.CHEAPEST, preference_assumed=False,
                   received_at=datetime.now(UTC)), None


def adopted_row(store: Store) -> dict:
    """What adopt() stores from our quote mail: carrier name, total, currency. Nothing else."""
    store.upsert_rfq("30362", "30362", "sonnberg-roesterei@hackloop.mail", "Air freight quote request to LAX",
                     datetime.now(UTC), "QUOTED")
    store.update_rfq("30362", status="QUOTED", carrier="Polaris Air Logistics", total="4455.22", currency="EUR",
                     quoted_at=time.time())
    row = store._conn.execute("SELECT * FROM rfqs WHERE id='30362'").fetchone()
    cols = [d[0] for d in store._conn.execute("SELECT * FROM rfqs LIMIT 0").description]
    return dict(zip(cols, row, strict=False))


def make(client, portal) -> BookingAgent:
    settings = replace(SETTINGS, base_url=BASE, dry_run=False, kill_switch=False)
    return BookingAgent(client, settings, portal=portal, directory=load_directory(KIT))


class Outbound:
    def __init__(self) -> None:
        self.sent: list[tuple] = []

    async def send_new(self, to, subject, body):
        self.sent.append((to, subject, body))


@respx.mock
async def test_round_103_books_on_the_portal_with_a_fresh_rate(tmp_path) -> None:
    respx.post(f"{BASE}/v1/portal/bookings").mock(return_value=httpx.Response(
        201, json={"booking_reference": "BK-ABCDEFGH", "rate_id": "R-FRESHrate0001", "status": "booked",
                   "price": "4455.22", "currency": "EUR"}))
    store = Store(tmp_path / "s.db")
    orch = Orch(store)
    orch.extractor = Extractor()
    orch.mailbox.stored[30362] = SimpleNamespace(id=30362, subject="s", body="b", sender="c@x")
    portal = FakePortal()
    async with httpx.AsyncClient() as client:
        booker = make(client, portal)
        booker.outbound = Outbound()
        booking = await booker.book(orch, adopted_row(store), {})
    assert booking is not None and booking["booking_reference"] == "BK-ABCDEFGH"
    assert booking["origin"] == "STR" and booking["destination"] == "LAX"
    assert "PL" in portal.asked and "Polaris Air Logistics" not in portal.asked
    assert booker.outbound.sent == []  # no empty booking mail to the airline


@respx.mock
async def test_no_empty_route_mail_when_nothing_can_be_read(tmp_path) -> None:
    store = Store(tmp_path / "s.db")
    orch = Orch(store)
    orch.extractor = Extractor(fail=True)
    orch.mailbox.stored[30362] = SimpleNamespace(id=30362, subject="s", body="b", sender="c@x")

    class NoPortal(FakePortal):
        async def _ports_data(self, deadline):
            raise RuntimeError("portal down")

    async with httpx.AsyncClient() as client:
        booker = make(client, NoPortal())
        booker.outbound = Outbound()
        booking = await booker.book(orch, adopted_row(store), {})
    assert booking is None  # a person books it (HOLD), instead of "Route:  to ."
    assert booker.outbound.sent == []


@respx.mock
async def test_email_booking_still_used_when_route_is_known(tmp_path) -> None:
    store = Store(tmp_path / "s.db")
    orch = Orch(store)
    orch.extractor = Extractor()
    orch.mailbox.stored[30362] = SimpleNamespace(id=30362, subject="s", body="b", sender="c@x")

    class Silent(FakePortal):
        async def rate_for(self, rfq, airline):
            return None

    async with httpx.AsyncClient() as client:
        booker = make(client, Silent())
        booker.outbound = Outbound()
        booking = await booker.book(orch, adopted_row(store), {})
    assert booking is not None and booking["method"] == "email"
    [(to, subject, body)] = booker.outbound.sent
    assert "Route: STR to LAX." in body
