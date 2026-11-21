from decimal import Decimal as D

import pytest

from sourcing.kit import airport_for_zone, build, load_carriers, load_pickup_zones, zone_for_postcode
from sourcing.kit_parsers import parse_tariff_lines

TARIFFS, PROBLEMS = build(out=None)


def lane(airline, o, d):
    t = next(t for t in TARIFFS if t.airline.startswith(airline))
    return t, next(l for l in t.lanes if (l.origin, l.destination) == (o, d))


def rates(l):
    return {int(b.from_kg): b.rate_per_kg for b in l.breaks}


def fuel_sec(l):
    return [s.amount for s in l.surcharges]


def test_all_ten_sheets_parse_without_problems():
    assert PROBLEMS == []
    assert len(TARIFFS) == 10
    assert sum(len(t.lanes) for t in TARIFFS) == 158
    for t in TARIFFS:
        assert t.currency == "EUR"
        assert str(t.valid_from) == "2026-11-01" and str(t.valid_to) == "2026-11-30"
        assert t.kg_per_cbm == D(167) and t.surcharge_weight == "billed"


# one hand-checked lane per file format / layout
@pytest.mark.parametrize(
    "airline,o,d,transit,minimum,r,fs",
    [
        ("Cobalt", "STR", "YYZ", 4, "72.00", {0: "3.08", 45: "2.22", 2000: "0.77"}, ["0.71", "0.17"]),  # pdf blocks
        ("Orion", "FRA", "NBO", 4, "96.46", {0: "4.56", 45: "4.01", 1000: "1.64"}, ["1.00", "0.17"]),  # pdf blocks
        ("Helix", "MUC", "SGN", 6, "65.00", {250: "3.07", 2000: "1.55"}, ["1.32", "0.24"]),  # pdf table
        ("Danube", "FRA", "DXB", 2, "138.86", {45: "2.23", 1000: "1.33"}, ["1.12", "0.22"]),  # scan
        ("Elbflug", "STR", "PVG", 4, "112.00", {0: "4.72", 1000: "1.37"}, ["1.24", "0.10"]),  # xlsx sections
        ("Kestrel", "DUS", "NRT", 2, "113.42", {250: "2.78", 2000: "1.17"}, ["1.31", "0.21"]),  # xlsx inline sc
        ("Vega", "CGN", "LOS", 3, "114.48", {0: "4.6", 2000: "1.69"}, ["1.29", "0.13"]),  # xlsx numbers
        ("Wayzata", "STR", "SGN", 5, "71", {300: "2.6", 1000: "1.82"}, ["0.95", "0.12"]),  # xlsx lane col
        ("Quetzal", "STR", "SCL", 2, "111.30", {1000: "2.39", 2000: "2.39"}, ["1.23", "0.24"]),  # docx
        ("Yellowtail", "CGN", "SYD", 5, "75.00", {0: "5.92", 2000: "1.54"}, ["0.76", "0.21"]),  # txt
    ],
)
def test_lane_values(airline, o, d, transit, minimum, r, fs):
    _, l = lane(airline, o, d)
    assert l.transit_days == transit
    assert l.min_charge == D(minimum)
    got = rates(l)
    for k, v in r.items():
        assert got[k] == D(v), (airline, k)
    assert fuel_sec(l) == [D(x) for x in fs]


def test_unreadable_row_is_a_problem_not_a_guess():
    lines = [
        "Test Air | Air export tariff",
        "Currency EUR",
        "Lane  Transit  Minimum  -45  +45  +100",
        "FRA-JFK  2  80,00  3,00  57;  1,50",  # OCR garbage in one cell
        "FRA-JFK: fuel 1,00 per kg, security 0,20 per kg",
    ]
    t, problems = parse_tariff_lines(lines)
    assert t.lanes == [] and problems


def test_carriers_and_zones():
    carriers = load_carriers()
    airlines = [c for c in carriers if c.kind == "airline"]
    truckers = [c for c in carriers if c.kind == "trucker"]
    assert len(airlines) == 29 and len(truckers) == 22
    cobalt = next(c for c in airlines if c.name == "Cobalt Skylift")
    assert cobalt.airline_code == "cobalt-skylift" and "JFK" in cobalt.destinations
    zones = load_pickup_zones()
    assert zone_for_postcode("60311") == "60"
    assert airport_for_zone("60", zones) == "FRA" and airport_for_zone("93", zones) == "MUC"
