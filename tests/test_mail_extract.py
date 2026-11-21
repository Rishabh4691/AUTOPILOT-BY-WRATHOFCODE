from decimal import Decimal

import pytest

from mail import extract as ex
from mail import kit
from mail.config import ROOT, settings

KIT = ROOT / "data" / "kit"
needs_kit = pytest.mark.skipif(not (KIT / "carrier-list.csv").exists(), reason="start kit not downloaded")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(kit, "settings", settings.__class__(kit_dir=KIT))
    kit.carriers.cache_clear()
    kit.pickup_zones.cache_clear()


def run(body, subject="Request", sender="Anna Kowalska <anna.kowalska@customer.mail>"):
    return ex.extract(subject, body, sender, "RFQ-1")


@needs_kit
def test_english_pallets_with_dims():
    x = run(
        "Hi team,\n\nplease quote air freight MUC to JFK.\n3 pallets 120x80x100 cm, total gross weight 450 kg.\n"
        "Cheapest option please.\n\nThanks,\nAnna",
        subject="Quote MUC-JFK",
    )
    s = x.shipment
    assert (s.origin, s.destination) == ("MUC", "JFK")
    assert x.pieces == 3 and x.gross_kg == 450
    assert x.chargeable_kg == 481.0
    assert x.preference == "cheapest" and x.first_name == "Anna" and x.language == "en"
    assert not s.door_pickup


@needs_kit
def test_german_lines_with_weight_each_and_pickup():
    x = run(
        "Hallo,\n\nbitte um ein Angebot Luftfracht nach Chicago (ORD).\n"
        "2 Kolli à 60 x 40 x 50 cm, je 35 kg\n1 Palette 120 x 80 x 150 cm, 210 kg je\n"
        "Abholung bei uns in 80331 München. Es ist eilig, bitte die schnellste Verbindung.\n\nViele Grüße\nLukas Weber",
        subject="Anfrage Luftfracht",
        sender="lukas.weber@maschinen.mail",
    )
    s = x.shipment
    assert (s.origin, s.destination) == ("MUC", "ORD")
    assert x.pieces == 3
    assert x.gross_kg == 280
    assert s.door_pickup and s.pickup_zone == "80" and s.pickup_postcode == "80331"
    assert x.preference == "fastest" and x.language == "de" and x.first_name == "Lukas"


@needs_kit
def test_french_imperial_units():
    x = run(
        "Bonjour,\n\nmerci de nous faire une cotation fret aérien de FRA à DXB.\n"
        "4 cartons 24 x 20 x 18 in, poids total 220 lbs.\n\nCordialement,\nSophie",
        subject="Demande de devis",
        sender="sophie@luxe.mail",
    )
    s = x.shipment
    assert (s.origin, s.destination) == ("FRA", "DXB")
    assert s.pieces[0].dim_unit == "in" and s.weight_unit == "lb"
    assert x.gross_kg == pytest.approx(99.79, abs=0.01)
    vol_cbm = 4 * 24 * 20 * 18 * 2.54**3 / 1e6
    assert x.chargeable_kg == pytest.approx(max(99.79, vol_cbm * 167), abs=0.5)
    assert x.language == "fr" and x.first_name == "Sophie"


@needs_kit
def test_spanish_labelled_fields():
    x = run(
        "Hola,\n\nOrigen: Frankfurt\nDestino: GRU\nBultos: 5 bultos 50x50x50 cm\nPeso bruto total: 1.250 kg\n"
        "Necesitamos la opción más barata.\n\nSaludos,\nCarlos",
        subject="Cotización carga aérea",
        sender="carlos@export.mail",
    )
    s = x.shipment
    assert (s.origin, s.destination) == ("FRA", "GRU")
    assert x.gross_kg == 1250
    assert x.chargeable_kg == 1250
    assert x.preference == "cheapest" and x.language == "es"


@needs_kit
def test_italian_compact_lane_and_mm():
    x = run(
        "Ciao, ci serve un preventivo DUS-SIN: 2 colli 1200x800x900 mm, peso totale 300 kg. Grazie,\nGiulia",
        subject="Preventivo",
        sender="giulia@moda.mail",
    )
    s = x.shipment
    assert (s.origin, s.destination) == ("DUS", "SIN")
    assert s.pieces[0].length == Decimal("120")
    assert x.chargeable_kg == 289.0 or x.chargeable_kg == 300.0
    assert x.chargeable_kg == max(300.0, float(ex.chargeable_weight_kg(s)))
    assert x.language == "it"


@needs_kit
def test_weight_only_no_dims():
    x = run("Need a price STR to NRT for one crate, 85 kg. Thanks, Ken", subject="Air quote", sender="ken@tools.mail")
    assert (x.shipment.origin, x.shipment.destination) == ("STR", "NRT")
    assert x.chargeable_kg == 85.0
    assert "no dimensions given, chargeable = gross" in x.problems


@needs_kit
def test_missing_route_is_reported():
    x = run("Hello, we have 2 pallets 120x80x100 cm, 400 kg. Can you quote?", sender="someone@co.mail")
    assert x.shipment is None and "destination" in x.missing


@needs_kit
def test_quoted_history_is_ignored():
    body = "Please quote FRA to ORD, 1 box 40x40x40 cm, 12 kg.\n\nOn Fri, Bob wrote:\n> old request MUC-SIN 900 kg"
    x = run(body)
    assert (x.shipment.origin, x.shipment.destination) == ("FRA", "ORD")
    assert x.gross_kg == 12


@needs_kit
def test_preference_stated_or_assumed():
    assert run("Quote MUC to JFK, 1 box 40x40x40 cm, 12 kg, cheapest please").preference_stated
    assert not run("Quote MUC to JFK, 1 box 40x40x40 cm, 12 kg").preference_stated


def test_first_name_from_display_name_or_address():
    assert ex.find_first_name("Anna Kowalska <a.k@x.mail>", "no sign-off") == "Anna"
    assert ex.find_first_name("lukas.weber@x.mail", "") == "Lukas"
    assert ex.find_first_name("info@x.mail", "") == ""


def test_number_formats():
    assert ex.num("1.250") == 1250 and ex.num("1,250") == 1250 and ex.num("12,5") == Decimal("12.5") and ex.num("99.5") == Decimal("99.5")
