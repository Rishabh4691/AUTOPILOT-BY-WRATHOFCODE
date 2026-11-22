from datetime import UTC, datetime
from decimal import Decimal

from core.agents import limits
from core.contracts import RFQ, Piece, Preference, PriceOption
from mail.extract import tallest_cm


def rfq(height=100, notes=()):
    return RFQ(
        mail_id=1,
        thread_root_id=1,
        customer="a@b",
        subject="Quote",
        origin="FRA",
        destination="JFK",
        pieces=(
            Piece(count=1, length_cm=Decimal(120), width_cm=Decimal(80), height_cm=Decimal(height)),
        ),
        gross_kg=Decimal(300),
        door_pickup=False,
        preference=Preference.CHEAPEST,
        preference_assumed=False,
        received_at=datetime.now(UTC),
        notes=tuple(notes),
    )


def option(carrier, total):
    return PriceOption(
        source="portal", carrier=carrier, total=Decimal(total), currency="EUR", transit_days=2
    )


def test_tall_piece_skips_airline_with_height_limit(monkeypatch):
    monkeypatch.setattr(
        limits,
        "airline_limits",
        lambda: {"bellyair": (Decimal(160), None), "bigfreighter": (Decimal(300), None)},
    )
    keep, dropped = limits.usable(
        [option("Belly Air", "900"), option("Big Freighter", "1100")], rfq(180)
    )
    assert [o.carrier for o in keep] == ["Big Freighter"] and "180" in dropped[0]


def test_lithium_skips_airline_that_refuses_un3480(monkeypatch):
    monkeypatch.setattr(limits, "airline_limits", lambda: {"nolith": (None, False)})
    keep, dropped = limits.usable(
        [option("No Lith", "900"), option("Other", "1000")], rfq(notes=("UN3480",))
    )
    assert [o.carrier for o in keep] == ["Other"] and dropped


def test_never_empty_when_everything_is_filtered(monkeypatch):
    monkeypatch.setattr(limits, "airline_limits", lambda: {"bellyair": (Decimal(160), None)})
    keep, _ = limits.usable([option("Belly Air", "900")], rfq(200))
    assert [o.carrier for o in keep] == ["Belly Air"]


def test_tallest_from_lots_and_tables():
    assert (
        tallest_cm("Lot 1: 2 pallets, each 120 x 80 x 175 cm\nLot 2: 1 crate, 60 x 60 x 60 cm")
        == 175
    )
    assert tallest_cm("Height (cm) | Gross weight (kg)\nHeight: 147") == 147
    assert limits.tallest(rfq(100, notes=("tallest_cm: 182",))) == 182
