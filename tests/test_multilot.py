"""Several shipments in one request, and replies accepting only part of them (roadmap section 18).

Real rounds 7-9 used "Lot 1 / Lot 2" for ONE consignment on one route; those must stay single.
"""

import json
from pathlib import Path

import pytest

from core.agents.booking import is_acceptance
from mail.multilot import lots, partial_acceptance

FIXTURES = Path(__file__).parent / "core" / "fixtures" / "mail"

MULTI = [
    "Lot 1: 2 cartons, 120 kg, 0.6 cbm, at our Berlin site 10115 Berlin, ready 27.11.2026.\n"
    "Lot 2: 1 pallet, 400 kg, 1.5 cbm, at our Hamburg warehouse 20457 Hamburg, ready 30.11.2026.\nPlease collect both.",
    "Cheapest from FRA.\nShipment A: 3 pieces, 300 kg, 1.2 cbm to ORD.\nShipment B: 2 pieces, 150 kg, 0.8 cbm to PVG.",
    "Please quote 5 pieces / 500 kg / 2 cbm MUC to ATL, and 4 pieces / 250 kg / 1 cbm HAM to DEL.",
    "First batch 3 pcs, 200 kg, 1 cbm ready 24.11.2026; second batch 2 pcs, 100 kg, 0.5 cbm ready 01.12.2026.",
]
SINGLE = [
    "Please quote cheapest FRA to ORD. 2 pallets 300 kg and 1 carton 50 kg, total 350 kg, 1.6 cbm, 3 pieces.",
    "Our head office in Berlin asked for the fastest option MUC to ATL. 5 pieces, 500 kg, 2 cbm.",
    "Please collect 4 pallets, 800 kg, 3 cbm from 60311 Frankfurt and fly them cheapest to PVG.",
]


@pytest.mark.parametrize("body", MULTI)
def test_several_shipments_are_spotted(body: str) -> None:
    assert lots(body) == 2


@pytest.mark.parametrize("body", SINGLE)
def test_one_shipment_stays_single(body: str) -> None:
    assert lots(body) == 1


@pytest.mark.parametrize("name", ["real_rfq_1639.json", "real_rfq_1978.json", "fuzz_9086.json"])
def test_real_lot_lists_and_quoted_history_stay_single(name: str) -> None:
    assert lots(json.loads((FIXTURES / name).read_text())["body"]) == 1


@pytest.mark.parametrize("reply", [
    "Please book parcel A only, hold parcel B for now.",
    "Yes for the ORD lot, but not the PVG one.",
    "Go ahead with the first batch only.",
    "Book shipment A, we cancel shipment B.",
])
def test_partial_acceptance_does_not_book_everything(reply: str) -> None:
    assert partial_acceptance(reply) and not is_acceptance(reply)


@pytest.mark.parametrize("reply", [
    "Yes, please book.", "Perfect, book it!", "Ja, bitte buchen.",
    "Yes, book it, but not too late please.", "Yes please book, but not before Monday.",
    "Yes please, go ahead and book it under our reference.",
])
def test_plain_yes_still_books(reply: str) -> None:
    assert is_acceptance(reply)
