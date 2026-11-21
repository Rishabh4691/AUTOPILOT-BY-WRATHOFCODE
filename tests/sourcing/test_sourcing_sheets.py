from datetime import date
from decimal import Decimal as D

from sourcing.kit import build
from sourcing.models import Break, Shipment, Tariff, TariffLane
from sourcing.sheets import get_sheet_prices, price_lane, sheet_options
from sourcing.weights import chargeable_weight_kg, round_up, sanity_problems

NOV = date(2026, 11, 21)
TARIFFS, _ = build(out=None)  # parse the real start kit once


def ship(**kw) -> Shipment:
    base = dict(rfq_id="T", origin="CGN", destination="SYD")
    base.update(kw)
    return Shipment(**base)


def yellowtail_cgn_syd():
    t = next(t for t in TARIFFS if t.airline == "Yellowtail Air Freight")
    lane = next(l for l in t.lanes if (l.origin, l.destination) == ("CGN", "SYD"))
    return t, lane


# ------------------------------------------------------------------ weights
def test_round_up_half_kg():
    assert round_up(D("320.64")) == D("321.0")
    assert round_up(D("321")) == D("321")
    assert round_up(D("0.1")) == D("0.5")


def test_volume_weight_wins_with_167_per_cbm():
    s = ship(pieces=[{"count": 2, "length": 120, "width": 80, "height": 100}], gross_weight=300)
    # 2 x 0.96 m3 = 1.92 m3 x 167 = 320.64 kg -> 321.0
    assert chargeable_weight_kg(s, kg_per_cbm=D("167")) == D("321.0")


def test_inches_and_pounds():
    s = ship(
        pieces=[{"count": 1, "length": 40, "width": 40, "height": 40, "dim_unit": "in"}],
        gross_weight=220,
        weight_unit="lb",
    )
    # 220 lb = 99.79 kg; 40in cube = 1.0488 m3 -> 175.15 kg at 167/m3
    assert chargeable_weight_kg(s, kg_per_cbm=D("167")) == D("175.5")


def test_sanity_flags_lb_kg_mixup():
    s = ship(pieces=[{"count": 1, "length": 10, "width": 10, "height": 10}], gross_weight=500)
    assert any("density" in p for p in sanity_problems(s))


# ------------------------------------------------------------------ pricing
def test_cheat_sheet_next_break_is_cheaper():
    t = Tariff(
        tariff_id="X",
        airline_code="x",
        airline="X",
        currency="EUR",
        lanes=[
            TariffLane(
                origin="CGN",
                destination="SYD",
                breaks=[Break(from_kg=D(500), rate_per_kg=D("2.10")), Break(from_kg=D(1000), rate_per_kg=D("1.85"))],
            )
        ],
    )
    s = ship(gross_weight=995)
    o = price_lane(t, t.lanes[0], s)
    assert o.billed_weight_kg == D(1000) and o.total == D("1850.00")


def test_real_lane_by_hand():
    # Yellowtail CGN-SYD, 321 kg chargeable -> +250 bracket at 3.02
    # freight 321 x 3.02 = 969.42; fuel+security (0.76+0.21) x 321 = 311.37
    t, lane = yellowtail_cgn_syd()
    s = ship(pieces=[{"count": 2, "length": 120, "width": 80, "height": 100}], gross_weight=300)
    o = price_lane(t, lane, s)
    assert o.chargeable_weight_kg == D("321.0")
    assert o.total == D("1280.79")
    assert o.transit_days == 5


def test_real_lane_bumps_to_next_break_with_surcharges_on_billed_weight():
    # 230 kg: 230 x 3.87 + 230 x 0.97 = 1113.20, but 250 x 3.02 + 250 x 0.97 = 997.50
    t, lane = yellowtail_cgn_syd()
    o = price_lane(t, lane, ship(gross_weight=230))
    assert o.billed_weight_kg == D("250") and o.total == D("997.50")
    assert "billed as 250" in o.notes[0]


def test_minimum_charge_applies_to_freight_only():
    # 10 kg x 5.92 = 59.20 < minimum 75.00; surcharges 10 x 0.97 = 9.70
    t, lane = yellowtail_cgn_syd()
    o = price_lane(t, lane, ship(gross_weight=10))
    assert o.total == D("84.70")
    assert o.lines[0].basis == "minimum"


def test_get_sheet_prices_lists_every_airline_on_the_lane_cheapest_first():
    s = Shipment(rfq_id="T", origin="FRA", destination="DXB", gross_weight=400)
    opts = get_sheet_prices(s, TARIFFS)
    names = [o.airline for o in opts]
    assert set(names) == {"Elbflug Air Freight", "Danube Wings Cargo"}
    assert [o.total_eur for o in opts] == sorted(o.total_eur for o in opts)


def test_unknown_lane_gives_nothing():
    assert get_sheet_prices(ship(origin="FRA", destination="ULN", gross_weight=50), TARIFFS) == []


def test_dict_input_and_height_rule():
    t, lane = yellowtail_cgn_syd()
    t2 = t.model_copy(update={"max_piece_height_cm": D(160)})
    rfq = {"rfq_id": "T", "origin": "CGN", "destination": "SYD", "gross_weight": 100,
           "pieces": [{"length": 100, "width": 100, "height": 170}]}
    opts, skipped = sheet_options(rfq, [t2])
    assert opts == [] and "piece height" in skipped[0]
