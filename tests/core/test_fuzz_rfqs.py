"""Fake RFQs from the fuzz rounds. Each one failed before its fix."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from core.agents.attachments import dangerous_goods
from core.agents.extractor import RegexRfqExtractor
from core.agents.mailbox import parse_mail
from core.agents.rules_extractor import RulesFirstExtractor
from core.agents.sheets import SheetPriceSource
from core.config import load_settings
from core.contracts import RFQ, Preference
from core.pricing.weight import chargeable_kg
from mail.dg import check
from mail.text import fresh_text

FIXTURES = Path(__file__).parent / "fixtures" / "mail"

EXPECTED: dict[int, dict[str, object]] = {
    9001: {
        "origin": "MUC",
        "dest": "DXB",
        "gross": 630.0,
        "vol": None,
        "charge": 630.0,
        "door": True,
        "zone": "85",
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-24",
        "dg": False,
    },
    9002: {
        "origin": "FRA",
        "dest": "ORD",
        "gross": 598.742,
        "charge": 599.0,
        "door": False,
        "zone": None,
        "pref": "fastest",
        "cur": "USD",
        "ready": "2026-11-25",
        "dg": False,
    },
    9003: {
        "origin": "DUS",
        "dest": "NBO",
        "gross": 412.0,
        "vol": 2.8,
        "charge": 468.0,
        "door": True,
        "zone": "40",
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-26",
        "dg": False,
    },
    9004: {
        "origin": "STR",
        "dest": "BOG",
        "gross": 356.0,
        "vol": 1.9,
        "charge": 356.0,
        "door": False,
        "pref": "fastest",
        "cur": "EUR",
        "ready": "2026-11-27",
        "dg": False,
    },
    9005: {"dg": True},
    9006: {
        "origin": "HAM",
        "dest": "ICN",
        "gross": 960.0,
        "charge": 960.0,
        "door": True,
        "zone": "22",
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-25",
        "dg": False,
    },
    9011: {"dg": True},
    9014: {
        "origin": "MUC",
        "dest": "BOM",
        "gross": 1100.0,
        "charge": 1100.0,
        "door": False,
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-30",
        "dg": False,
    },
    9018: {
        "origin": "FRA",
        "dest": "LIM",
        "gross": 135.0,
        "charge": 135.0,
        "door": True,
        "zone": "63",
        "pref": "fastest",
        "cur": "USD",
        "ready": "2026-11-25",
        "dg": False,
    },
    9019: {
        "origin": "STR",
        "dest": "JFK",
        "gross": 600.0,
        "charge": 600.0,
        "door": True,
        "zone": "73",
        "pref": "fastest",
        "cur": "CHF",
        "ready": "2026-11-26",
        "dg": False,
    },
    9034: {
        "origin": "MUC",
        "dest": "DEL",
        "gross": 410.0,
        "vol": 1.5,
        "charge": 410.0,
        "door": True,
        "zone": "80",
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-26",
        "dg": False,
    },
    9039: {
        "origin": "MUC",
        "dest": "HKG",
        "gross": 180.0,
        "vol": 0.9,
        "charge": 180.0,
        "door": True,
        "zone": "86",
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-24",
        "dg": False,
    },
    9041: {
        "origin": "STR",
        "dest": "SYD",
        "gross": 750.0,
        "charge": 750.0,
        "door": False,
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-27",
        "dg": False,
    },
    9051: {
        "origin": "FRA",
        "dest": "NBO",
        "gross": 220.0,
        "vol": 1.0,
        "charge": 220.0,
        "door": True,
        "zone": "60",
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-25",
        "dg": False,
    },
    9052: {
        "origin": "MUC",
        "dest": "ICN",
        "gross": 260.0,
        "vol": 1.2,
        "charge": 260.0,
        "door": False,
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-26",
        "dg": False,
    },
    9053: {
        "origin": "FRA",
        "dest": "TNR",
        "gross": 95.0,
        "charge": 95.0,
        "door": False,
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-26",
        "dg": False,
    },
    9054: {
        "origin": "HAJ",
        "dest": "DXB",
        "gross": 350.0,
        "vol": 1.1,
        "charge": 350.0,
        "door": False,
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-24",
        "dg": False,
    },
    9056: {
        "origin": "STR",
        "dest": "BKK",
        "gross": 480.0,
        "charge": 480.0,
        "door": True,
        "zone": "71",
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-27",
        "dg": False,
    },
    9057: {
        "origin": "FRA",
        "dest": "GRU",
        "gross": 500.0,
        "vol": 3.0,
        "charge": 501.0,
        "door": False,
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-28",
        "dg": False,
    },
    9072: {
        "origin": "DUS",
        "dest": "BOM",
        "gross": 812.0,
        "vol": 3.3,
        "charge": 812.0,
        "door": False,
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-27",
        "dg": False,
    },
    9073: {
        "origin": "MUC",
        "dest": "ORD",
        "gross": 520.0,
        "vol": 2.2,
        "charge": 520.0,
        "door": True,
        "zone": "86",
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-30",
        "dg": False,
    },
    9081: {
        "origin": "HAM",
        "dest": "SIN",
        "gross": 210.0,
        "vol": 0.8,
        "charge": 210.0,
        "door": False,
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-25",
        "dg": False,
    },
    9083: {
        "origin": "FRA",
        "dest": "DXB",
        "gross": 380.0,
        "vol": 1.8,
        "charge": 380.0,
        "door": False,
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-26",
        "dg": False,
    },
    9086: {
        "origin": "STR",
        "dest": "BKK",
        "gross": 260.0,
        "vol": 1.1,
        "charge": 260.0,
        "door": False,
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-27",
        "dg": False,
    },
    9092: {
        "origin": "DUS",
        "dest": "NBO",
        "gross": 600.0,
        "vol": 4.8,
        "charge": 802.0,
        "door": False,
        "pref": "cheapest",
        "cur": "EUR",
        "ready": "2026-11-26",
        "dg": False,
    },
}


@pytest.fixture(autouse=True)
def _no_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import mail.extract

    monkeypatch.setattr(mail.extract, "MEMORY_PATH", tmp_path / "customers.json")


@pytest.mark.parametrize("mail_id", sorted(EXPECTED))
async def test_fuzz_rfq(mail_id: int) -> None:
    expected = EXPECTED[mail_id]
    raw = json.loads((FIXTURES / f"fuzz_{mail_id}.json").read_text(encoding="utf-8"))
    mail = parse_mail(raw)
    got: dict[str, object] = {"dg": check(fresh_text(mail.body), []).dangerous}
    if expected.get("dg") is False:
        assert dangerous_goods(fresh_text(mail.body)) is None
    if set(expected) - {"dg"}:
        settings = load_settings(environ={"FIVEU_API_KEY": "k"})
        rfq, _ = await RulesFirstExtractor(RegexRfqExtractor(settings, None)).extract(mail)
        got.update(
            origin=rfq.origin,
            dest=rfq.destination,
            gross=float(rfq.gross_kg),
            vol=None if rfq.volume_cbm is None else float(rfq.volume_cbm),
            charge=float(chargeable_kg(rfq.gross_kg, rfq.pieces, rfq.volume_cbm)),
            door=rfq.door_pickup,
            zone=rfq.pickup_zone,
            pref=rfq.preference.value,
            cur=rfq.currency,
            ready=str(rfq.ready_date) if rfq.ready_date else None,
        )
    for key, want in expected.items():
        if isinstance(want, float):
            assert got[key] == pytest.approx(want, abs=0.01), key
        else:
            assert got[key] == want, key


TARIFFS = Path(__file__).resolve().parents[2] / "data" / "tariffs.json"


def _rfq(ready: date, door: bool) -> RFQ:
    return RFQ(
        mail_id=1,
        thread_root_id=1,
        customer="test-30@hackloop.mail",
        subject="Air freight quote to JFK",
        origin="FRA",
        destination="JFK",
        pieces=(),
        gross_kg=Decimal("500"),
        volume_cbm=Decimal("1"),
        door_pickup=door,
        pickup_zone="60" if door else None,
        preference=Preference.CHEAPEST,
        preference_assumed=True,
        ready_date=ready,
        received_at=datetime(2026, 11, 21, tzinfo=UTC),
    )


async def test_sheet_not_used_when_door_pickup_departs_after_validity() -> None:
    kit = TARIFFS
    if not kit.exists():
        pytest.skip("no rate sheets")
    sheets = SheetPriceSource()
    assert await sheets.quote(_rfq(date(2026, 11, 30), door=False))
    assert await sheets.quote(_rfq(date(2026, 11, 30), door=True)) == []
    assert await sheets.quote(_rfq(date(2026, 12, 2), door=False)) == []
