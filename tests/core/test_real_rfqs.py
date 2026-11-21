import json
from decimal import Decimal
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


async def test_rfq_1639_sums_lots_and_respects_self_delivery() -> None:
    settings = load_settings(environ={"FIVEU_API_KEY": "k"})
    extractor = RulesFirstExtractor(RegexRfqExtractor(settings, None))
    rfq, _ = await extractor.extract(parse_mail(load("real_rfq_1639.json")))
    assert (rfq.origin, rfq.destination) == ("MUC", "LAX")
    assert rfq.gross_kg == Decimal("998")
    assert rfq.volume_cbm == Decimal("2.39")
    assert rfq.door_pickup is False
    assert rfq.preference.value == "fastest"


async def test_every_recorded_real_rfq_extracts() -> None:
    settings = load_settings(environ={"FIVEU_API_KEY": "k"})
    extractor = RulesFirstExtractor(RegexRfqExtractor(settings, None))
    files = sorted(FIXTURES.glob("real_rfq_*.json"))
    assert files
    for path in files:
        rfq, _ = await extractor.extract(parse_mail(load(path.name)))
        assert rfq.gross_kg > 0
        assert rfq.currency == "EUR"
        assert not rfq.door_pickup or rfq.pickup_zone is not None


async def test_rfq_1978_sums_mixed_lots_and_ignores_net_weight() -> None:
    settings = load_settings(environ={"FIVEU_API_KEY": "k"})
    extractor = RulesFirstExtractor(RegexRfqExtractor(settings, None))
    rfq, _ = await extractor.extract(parse_mail(load("real_rfq_1978.json")))
    assert (rfq.origin, rfq.destination) == ("FRA", "LOS")
    assert rfq.gross_kg == Decimal("1952")
    assert rfq.volume_cbm == Decimal("4.677")
    assert rfq.door_pickup and rfq.pickup_zone == "36"


def test_first_name_is_found_in_every_real_rfq() -> None:
    from mail.extract import find_first_name

    expected = {
        "276": "Sara",
        "432": "Anna",
        "742": "Tobias",
        "948": "Deniz",
        "1234": "Klaus",
        "1471": "Jonas",
        "1639": "Deniz",
        "1978": "Mira",
        "2268": "Klaus",
        "3328": "Petra",
    }
    for rfq_id, name in expected.items():
        raw = load(f"real_rfq_{rfq_id}.json")
        assert find_first_name(str(raw["from"]), str(raw["body"])) == name, rfq_id


def test_rfq_3638_without_address_uses_signature_city(tmp_path: Path, monkeypatch) -> None:
    import mail.extract as extract_module

    monkeypatch.setattr(extract_module, "MEMORY_PATH", tmp_path / "customers.json")
    later = load("real_rfq_3638.json")
    result = extract_module.extract(
        str(later["subject"]), str(later["body"]), str(later["from"]), "3638"
    )
    assert result.shipment is not None
    assert result.shipment.origin == "MUC"
    assert result.shipment.pickup_zone == "93"


def test_rfq_4930_signature_city_without_zone_maps_to_nearest_zone(
    tmp_path: Path, monkeypatch
) -> None:
    import mail.extract as extract_module

    monkeypatch.setattr(extract_module, "MEMORY_PATH", tmp_path / "customers.json")
    raw = load("real_rfq_4930.json")
    result = extract_module.extract(str(raw["subject"]), str(raw["body"]), str(raw["from"]), "4930")
    assert result.shipment is not None
    assert result.shipment.origin == "MUC"


def test_xlsx_pipe_packing_list_round_35() -> None:
    import mail.dg as dg
    from core.agents.rules_extractor import TOTAL_GROSS, TOTAL_VOLUME

    sheet = (
        "Total pieces: | 19\nTotal gross weight (kg): | 1751\n"
        "Total volume (cbm): | 11.97\nDangerous goods: | Not restricted"
    )
    assert TOTAL_GROSS.search(sheet).group(1) == "1751"  # type: ignore[union-attr]
    assert TOTAL_VOLUME.search(sheet).group(1) == "11.97"  # type: ignore[union-attr]
    assert not dg.check("", [("s.xlsx", sheet)]).dangerous
    assert not dg.check("", [("s.xlsx", "Dangerous goods: : Not restricted")]).dangerous
    assert dg.check("", [("s.xlsx", "Dangerous goods: | UN1263 paint")]).dangerous


def test_excluded_airline_is_never_quoted_or_named_round_42(tmp_path, monkeypatch) -> None:
    from datetime import UTC, datetime

    import mail.exclusions as ex
    from core.agents.human_writer import strip_excluded
    from core.agents.rules_extractor import with_exclusions
    from core.contracts import RFQ, PriceOption, Preference
    from core.orchestrator import drop_excluded

    monkeypatch.setattr(ex, "MEMORY_PATH", tmp_path / "ex.json")
    rfq = RFQ(
        mail_id=10831, thread_root_id=10831, customer="p@meyer.mail", subject="s", origin="FRA",
        destination="ULN", pieces=(), gross_kg=Decimal("911"), volume_cbm=Decimal("3.27"),
        door_pickup=False, preference=Preference.CHEAPEST, preference_assumed=False,
        received_at=datetime.now(UTC),
    )
    body = "Please do not offer Zephyr Steppe Cargo (ZS) for this shipment or for any of our future inquiries."
    rfq = with_exclusions(rfq, body, "p@meyer.mail")
    options = [
        PriceOption(source="bid", carrier="Zephyr Steppe Cargo", total=Decimal("2780"), currency="EUR", transit_days=5),
        PriceOption(source="bid", carrier="Lagoon Isles Airways", total=Decimal("3210"), currency="EUR", transit_days=3),
    ]
    assert [o.carrier for o in drop_excluded(rfq, options)] == ["Lagoon Isles Airways"]
    later = with_exclusions(rfq.model_copy(update={"notes": ()}), "New request, cheapest please.", "p@meyer.mail")
    assert [o.carrier for o in drop_excluded(later, options)] == ["Lagoon Isles Airways"]
    text = "Hi Petra,\n\nI left Zephyr Steppe Cargo out. Lagoon Isles Airways is the cheapest.\n\nKind regards"
    assert "Zephyr" not in strip_excluded(text, rfq)
    assert "Lagoon Isles Airways is the cheapest." in strip_excluded(text, rfq)
