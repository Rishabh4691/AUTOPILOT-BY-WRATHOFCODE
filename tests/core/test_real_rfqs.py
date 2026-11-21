import json
from pathlib import Path

from core.agents.directory import load_directory
from core.agents.extractor import RegexRfqExtractor
from core.agents.mailbox import parse_mail
from core.agents.rules_extractor import RulesFirstExtractor
from core.agents.trucker import request_body
from core.config import load_settings

FIXTURES = Path(__file__).parent / "fixtures" / "mail"
KIT = Path(__file__).parent / "fixtures" / "kit"


def load(name: str) -> dict[str, object]:
    raw: dict[str, object] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return raw


async def test_rfq_432_keeps_full_postcode_for_truckers() -> None:
    settings = load_settings(environ={"FIVEU_API_KEY": "k"})
    extractor = RulesFirstExtractor(RegexRfqExtractor(settings, None))
    rfq, usage = await extractor.extract(parse_mail(load("real_rfq_432.json")))
    assert (rfq.origin, rfq.destination) == ("FRA", "JFK")
    assert rfq.door_pickup and rfq.pickup_zone == "61"
    assert rfq.pickup_postcode == "61018"
    assert usage is None
    zone = load_directory(KIT).zone("61")
    assert zone is not None
    body = request_body(rfq, "61", zone.area, zone.airport)
    assert "61018" in body
    assert "10.78" in body
