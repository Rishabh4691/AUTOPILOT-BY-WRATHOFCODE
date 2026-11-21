"""Fake RFQs from the fuzz rounds. Each one failed before its fix."""

import json
from pathlib import Path

import pytest

from core.agents.attachments import dangerous_goods
from core.agents.extractor import RegexRfqExtractor
from core.agents.mailbox import parse_mail
from core.agents.rules_extractor import RulesFirstExtractor
from core.config import load_settings
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
        assert dangerous_goods(mail.body) is None
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
