import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core import orchestrator as orch_mod
from core.contracts import RFQ, Preference, PriceOption
from core.orchestrator import Orchestrator


def rfq(pref=Preference.CHEAPEST):
    return RFQ(
        mail_id=1,
        thread_root_id=1,
        customer="a@b",
        subject="Quote",
        origin="CGN",
        destination="EZE",
        pieces=(),
        gross_kg=Decimal(500),
        door_pickup=True,
        preference=pref,
        preference_assumed=False,
        received_at=datetime.now(UTC),
        notes=("site_unknown",),
    )


def opt(carrier, total, days):
    return PriceOption(
        source="sheet", carrier=carrier, total=Decimal(total), currency="EUR", transit_days=days
    )


class Sheets:
    name = "sheets"
    prices = {
        "STR": [opt("Nova Atlas", "4638.85", 7)],
        "MUC": [opt("Meridian", "5100", 3)],
        "FRA": [opt("Slow", "100", 1)],
    }

    async def quote(self, r):
        if r.origin == "FRA":
            await asyncio.sleep(5)
        return self.prices.get(r.origin, [])


class Pickup:
    def fallback_zone(self, r):
        return {"STR": "70", "MUC": "80", "FRA": "60"}.get(r.origin)


class Shell:
    sources = [Sheets()]
    pickup = Pickup()

    def __init__(self):
        self.events = []

    def emit(self, *a, **k):
        self.events.append(a[3])

    class store:
        @staticmethod
        def update_rfq(*a, **k):
            pass


@pytest.mark.parametrize(
    "pref,origin,zone", [(Preference.CHEAPEST, "STR", "70"), (Preference.FASTEST, "MUC", "80")]
)
async def test_best_airport_without_waiting_for_slow_answers(monkeypatch, pref, origin, zone):
    monkeypatch.setattr(orch_mod, "ORIGIN_COMPARE_S", 0.3)
    shell = Shell()
    best = await Orchestrator.best_origin(shell, rfq(pref))
    assert (best.origin, best.pickup_zone) == (origin, zone)
    assert "compared 2 airports" in shell.events[0]
