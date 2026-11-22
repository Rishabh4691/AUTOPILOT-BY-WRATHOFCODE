from __future__ import annotations

from pathlib import Path

from mail.multilot import split_shipments
from tests.core.test_orchestrator import NOW, drain, harness, mail

ROUND89 = (
    "Hi there,\n\nHope your week's going well! Could you quote the fastest air freight option for each of these two "
    "shipments? Both will be ready for pickup on 2026-11-23 at our site in Wiesbaden, Germany (postcode 65996). Please "
    "arrange the truck from our site to the airport as part of the quote.\n\n"
    "1. GRU (Sao Paulo, BR) — automotive sensors, 4 pieces, gross weight 1281 kg, volume 3.76 cbm.\n"
    "2. TLV (Tel Aviv, IL) — machine parts, 1 piece, gross weight 1812 kg, volume 5.75 cbm.\n\n"
    "Could you send both quotes in the same reply, with a separate all-in price in EUR for each shipment rather than "
    "a combined total?\n\nThanks for your help!\n\nPetra Hofmann\nExport Desk, Hofmann Textilwerk KG"
)


def test_round89_splits_into_two_shipments():
    shared, lots = split_shipments(ROUND89)
    assert len(lots) == 2
    assert "GRU" in lots[0] and "1281 kg" in lots[0]
    assert "TLV" in lots[1] and "1812 kg" in lots[1]
    assert "65996" in shared and "1281" not in shared


def test_one_consignment_in_lots_is_not_split():
    text = "Please quote FRA to JFK.\n\nLot 1: 2 pallets, 400 kg, 1.2 cbm\nLot 2: 1 crate, 300 kg, 0.9 cbm\n"
    assert split_shipments(text)[1] == []
    assert split_shipments("Please quote FRA to ORD, 100 kg, cheapest.")[1] == []


async def test_one_reply_with_a_price_per_shipment(tmp_path: Path):
    h = harness(tmp_path, now=NOW)
    h.orchestrator.route(mail(25799, subject="Air freight quote request: GRU and TLV", body=ROUND89))
    await drain(h)
    assert len(h.mailbox.sent) == 1
    reply = h.mailbox.sent[0]
    assert reply.in_reply_to == 25799
    assert reply.body.count("All-in price") == 2
    assert reply.body.startswith("Hi Petra,") and "WOC-25799" in reply.body
    assert "1. " in reply.body and "\n\n2. " in reply.body
    assert any(e.step == "lots" for e in h.sink.events)


async def test_normal_request_is_unchanged(tmp_path: Path):
    h = harness(tmp_path, now=NOW)
    h.orchestrator.route(mail(500))
    await drain(h)
    assert len(h.mailbox.sent) == 1
    assert not any(e.step == "lots" for e in h.sink.events)
