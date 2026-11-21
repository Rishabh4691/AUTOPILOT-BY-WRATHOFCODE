from decimal import Decimal

import pytest

from mail import kit
from mail.config import ROOT, settings
from mail.extract import extract

KIT = ROOT / "data" / "kit"
pytestmark = pytest.mark.skipif(not (KIT / "carrier-list.csv").exists(), reason="start kit not downloaded")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(kit, "settings", settings.__class__(kit_dir=KIT))
    kit.carriers.cache_clear()
    kit.pickup_zones.cache_clear()


def run(body, subject="Air freight quote"):
    x = extract(subject, body, "buyer@customer.mail", "1")
    return x


ROUND_9 = (
    "Hi,\n\nCould you quote the cheapest air freight option to LOS (Lagos, NG) for automotive sensors? "
    "Pickup is at our site in 36627 (Fulda), Germany, ready on 2026-11-29. Please arrange the truck to the "
    "airport and quote one all-in price in EUR.\n\n"
    "Lot 1: 4 drums, together 730 kg gross (642 kg net), together 1.68 cbm\n"
    "Lot 2: 4 cartons, each 48 kg gross (41 kg net), each 110 x 110 x 52 cm\n"
    "Lot 3: 5 cases, each 206 kg gross (191 kg net), each 120 x 100 x 8 cm\n\n"
    "Please book all lots as a single consignment under one air waybill.\n\nMira Petersen\nNordlicht Audio"
)


def test_live_round_9_lots_each_together_and_net_decoys():
    x = run(ROUND_9)
    assert x.gross_kg == 1952
    assert x.shipment.volume_cbm == pytest.approx(Decimal("4.6768"))
    assert x.chargeable_kg == 1952
    assert x.pieces == 13
    assert (x.shipment.origin, x.shipment.destination, x.shipment.pickup_zone) == ("FRA", "LOS", "36")


def test_live_round_7_two_lots_self_delivery():
    x = run(
        "Could you please quote the fastest air freight option from MUC to LAX? The cargo will be ready for "
        "pickup on 2026-11-29, and we will deliver it to Munich airport (MUC) ourselves.\n\n"
        "Lot 1: 1 piece, gross weight 618 kg, volume 0.74 cbm\nLot 2: 1 piece, gross weight 380 kg, volume 1.65 cbm\n"
    )
    assert (x.gross_kg, x.shipment.volume_cbm, x.shipment.door_pickup) == (998, Decimal("2.39"), False)


@pytest.mark.parametrize(
    "line,gross,cbm",
    [
        ("Lot 1: 2 pallets, each 350 kg gross, each 120 x 80 x 150 cm\nLot 2: 1 crate, 90 kg, 60 x 60 x 60 cm", 790, 2.88 + 0.216),
        ("Lot 1: 3 boxes, each 50 lbs, each 20 x 20 x 20 in\nLot 2: 1 box, 22 lbs, 10 x 10 x 10 in", 0.45359237 * 172, (3 * 8000 + 1000) * 2.54**3 / 1e6),
        ("- 2 pallets, net 300 kg, gross 340 kg each, 120x80x100 cm each\n- 1 pallet, 410 kg gross, 120x100x120 cm", 1090, 1.92 + 1.44),
        ("Lot 1: 6 cartons, 1.250 kg in total, 3.5 cbm in total\nLot 2: 2 crates, each 400 kg, each 1.2 cbm", 2050, 5.9),
        ("Lot 1: 10 cases, together 1,2 t gross, together 4 m3\nLot 2: 1 case, 80 kg, 100 x 100 x 100 cm", 1280, 5.0),
        ("Lot 1: 4 pallets each 1200 x 800 x 1000 mm, each 250 kg\nLot 2: 2 pallets, together 300 kg, together 1.5 cbm", 1300, 3.84 + 1.5),
    ],
)
def test_predicted_lot_variants(line, gross, cbm):
    x = run(f"Please quote FRA to JFK, cheapest.\n\n{line}\n\nThanks, Ana")
    assert float(x.gross_kg) == pytest.approx(float(gross), rel=1e-3)
    assert float(x.shipment.volume_cbm) == pytest.approx(cbm, rel=1e-3)


@pytest.mark.parametrize(
    "body,gross",
    [
        ("Quote MUC to SIN: 3 pallets 120x80x100 cm, net weight 400 kg, gross weight 455 kg.", 455),
        ("Quote MUC to SIN, 1.2 t gross, 2 pallets 120x80x100 cm.", 1200),
        ("Quote MUC to SIN, total weight 1,250 kg, 2 pallets 120x80x100 cm.", 1250),
        ("Quote MUC to SIN, Gesamtgewicht 1.250 kg brutto, 2 Paletten 120x80x100 cm.", 1250),
    ],
)
def test_single_shipment_weight_traps(body, gross):
    assert float(run(body).gross_kg) == pytest.approx(gross)


def test_cubic_feet_volume():
    x = run("Quote FRA to ORD, 500 kg, 100 cu ft, no dimensions.")
    assert float(x.shipment.volume_cbm) == pytest.approx(2.8317, rel=1e-3)


def test_dims_written_with_by():
    x = run("Quote FRA to ORD, 2 pallets 120 by 80 by 100 cm, total 300 kg.")
    assert x.pieces == 2 and float(x.chargeable_kg) >= 320
