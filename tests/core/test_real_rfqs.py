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
    from core.contracts import RFQ, Preference, PriceOption
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
    assert drop_excluded(rfq, [options[0]]) == []
    later = with_exclusions(rfq.model_copy(update={"notes": ()}), "New request, cheapest please.", "p@meyer.mail")
    assert [o.carrier for o in drop_excluded(later, options)] == ["Lagoon Isles Airways"]
    text = "Hi Petra,\n\nI left Zephyr Steppe Cargo out. Lagoon Isles Airways is the cheapest.\n\nKind regards"
    assert "Zephyr" not in strip_excluded(text, rfq)
    assert "Lagoon Isles Airways is the cheapest." in strip_excluded(text, rfq)


def test_chinese_door_pickup_round_72() -> None:
    from mail.extract import extract

    body = (
        "您好，\n\n希望您这周过得顺利！想请您帮忙看看一票发往 LIM（Lima, PE）的空运。这票货我们想走最便宜的方案。\n\n"
        "货物是汽车传感器，共 11 件，毛重 704 kg，体积 3.08 cbm。2026-11-23 可以提货，提货地点是我们在 Cologne, Germany 的场地，"
        "邮编 50978。麻烦您安排卡车上门提货并送到机场。\n\n能否请您报一个包含上门提货和空运的 EUR 全包价？谢谢！\n\n"
        "Petra Hofmann\nExport Desk, Hofmann Textilwerk KG"
    )
    x = extract("空运询价：Cologne → LIM", body, "hofmann-textilwerk@hackloop.mail", "20161")
    assert x.shipment is not None
    assert x.shipment.door_pickup is True


def test_insurance_premium_is_added_round_91() -> None:
    from mail.insurance import note_value, premium

    body = (
        "Could you quote the fastest air freight option from DUS to MEX (Mexico City, MX)? "
        "We'll deliver to DUS ourselves. The shipment is ready on 2026-11-29: 1 piece of printed "
        "marketing material, 176 kg gross, 1.26 cbm.\n\nPlease include cargo insurance in the all-in "
        "price, on the terms of our frame agreement: goods value 22000 EUR, insured at 110 % of that "
        "value, premium rate 0.40 %."
    )
    assert premium(body) == Decimal("96.80")
    assert note_value(("x", "insurance_premium: 96.80")) == Decimal("96.80")
    assert premium("Warenwert 15.000 EUR, bitte Versicherung inklusive, versichert zu 110 %, Prämiensatz 0,35 %.") == Decimal("57.75")
    assert premium("Please quote the cheapest option, 1497 kg and 13.89 cbm.") is None
    assert premium("We do not need insurance. Goods value 5000 EUR.") is None


def test_extra_charges_are_added_to_the_total() -> None:
    from mail import extras

    notes = extras.notes_for([
        {"label": "export handling fee", "fixed_eur": None, "percent_of_total": Decimal("2.5")},
        {"label": "documentation fee", "fixed_eur": Decimal("35"), "percent_of_total": None},
    ])
    total, labels = extras.apply(Decimal("1000.00"), notes)
    assert total == Decimal("1060.00")
    assert labels == ["export handling fee", "documentation fee"]
    assert not extras.worth_asking("1497 kg gross and 13.89 cbm, cheapest please.")
    assert extras.worth_asking("please add the 2.5 % handling fee")


def test_same_shipment_as_earlier_request_round_103(tmp_path, monkeypatch) -> None:
    from mail import repeat_request
    from mail.extract import extract

    monkeypatch.setattr(repeat_request, "PATH", tmp_path / "requests.json")
    earlier = (
        "Dear Sir or Madam,\n\nCould you please provide an all-in air freight quote in EUR from STR to MEL "
        "(Melbourne, AU)? The shipment will be ready on 2026-11-26, and we will deliver it to STR ourselves.\n\n"
        "The shipment consists of 6 pieces of printed marketing material, with a gross weight of 1841 kg and a "
        "total volume of 4.63 cbm.\n\nKind regards\nAnna Sonnberg"
    )
    repeat_request.remember("sonnberg-roesterei@hackloop.mail", "Air freight quote request: STR to MEL", earlier)
    new = (
        "Hello,\n\nCould you please quote the same shipment as in my earlier request, \"Air freight quote request: "
        "STR to MEL\", sent on 2026-11-21 at 23:18 UTC for destination MEL? The cargo and pickup details are "
        "unchanged, and you already have them from that request.\n\nThe new destination is LAX, and the shipment "
        "will be ready for pickup on 2026-11-29. Please send me an all-in price in EUR for the cheapest option."
    )
    rebuilt = repeat_request.rebuild("sonnberg-roesterei@hackloop.mail", "Air freight quote request to LAX", new)
    assert rebuilt is not None
    x = extract("Air freight quote request to LAX", rebuilt, "sonnberg-roesterei@hackloop.mail", "30362")
    assert x.shipment is not None
    assert (x.shipment.origin, x.shipment.destination) == ("STR", "LAX")
    assert x.shipment.gross_weight == Decimal("1841")
    assert str(x.shipment.ready_date) == "2026-11-29"
    assert x.shipment.door_pickup is False


def test_same_shipment_new_destination_fastest_round_104(tmp_path, monkeypatch) -> None:
    from mail import repeat_request
    from mail.extract import extract

    monkeypatch.setattr(repeat_request, "PATH", tmp_path / "requests.json")
    earlier = (
        "Dear Sir or Madam,\n\nCould you please quote an all-in price in EUR for an air freight shipment of machine "
        "parts to ATL (Atlanta, US)? The shipment consists of 11 pieces, with a gross weight of 585 kg and a volume "
        "of 5.01 cbm.\n\nThe goods will be ready for pickup on 2026-11-23 at our site in 40043 Duesseldorf, Germany. "
        "Please arrange the truck pickup and transport to the departure airport and include both in your quote.\n\n"
        "The goods must arrive at ATL no later than 2026-11-27. Among the options that meet this deadline, we will "
        "make our decision based on price.\n\nKind regards\nJonas Kessler"
    )
    who = "kessler-feinmechanik@hackloop.mail"
    repeat_request.remember(who, "Air freight quote request to ATL", earlier)
    repeat_request.remember(who, "Air freight quote request to SGN", "Please quote 1549 kg, 8.26 cbm to SGN (Ho Chi Minh City).")
    new = (
        "Hello,\n\nCould you please quote the same shipment as in my request \"Air freight quote request to ATL\", "
        "sent on 2026-11-21 at 23:24 UTC for ATL? The cargo and pickup details are unchanged, and you already have "
        "them from that request.\n\nThe new destination is BOM, and the shipment will be ready for pickup on "
        "2026-11-26. Please send me your all-in price in EUR for the fastest option."
    )
    text = repeat_request.rebuild(who, "Air freight quote to BOM", new)
    assert text is not None and "no later than" not in text
    x = extract("Air freight quote to BOM", text, who, "30548")
    s = x.shipment
    assert (s.origin, s.destination, s.gross_weight, s.door_pickup, s.pickup_postcode) == ("DUS", "BOM", Decimal("585"), True, "40043")
    assert str(s.ready_date) == "2026-11-26" and x.preference == "fastest"
    assert repeat_request.rebuild(who, "x", "same shipment as in my request \"Air freight quote request to LIM\"") is None
