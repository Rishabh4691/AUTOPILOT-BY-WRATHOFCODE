from decimal import Decimal as D

import pytest

from sourcing.bids import (
    BidTracker,
    Carrier,
    bid_option,
    bid_ref,
    bid_request_email,
    carriers_for,
    parse_amount,
    parse_bid_reply,
)
from sourcing.models import Shipment

S = Shipment(
    rfq_id="RFQ-7",
    origin="FRA",
    destination="JFK",
    pieces=[{"count": 2, "length": 120, "width": 80, "height": 100}],
    gross_weight=300,
    door_pickup=True,
    pickup_zone="60",
)
AIR = Carrier("Cobalt Skylift", "cobalt-skylift@hackloop.mail", "airline", "cobalt-skylift", ["JFK", "SYD"])
AIR2 = Carrier("Gannet Airways", "gannet-airways@hackloop.mail", "airline", "gannet-airways", ["LAX"])
TRUCK = Carrier("Taunusfracht", "taunusfracht@hackloop.mail", "trucker", zones=["22", "45", "60"])


@pytest.mark.parametrize(
    "text,value",
    [("1,234.50", "1234.50"), ("1.234,50", "1234.50"), ("1'234.50", "1234.50"),
     ("1 234,5", "1234.5"), ("980", "980"), ("12,50", "12.50"), ("2.105", "2105")],
)
def test_parse_amount(text, value):
    assert parse_amount(text) == D(value)


def test_carriers_for_destination_and_pickup_zone():
    chosen = carriers_for(S, [AIR, AIR2, TRUCK])
    assert chosen == [AIR, TRUCK]


def test_request_email_has_ref_and_weights():
    mail = bid_request_email(S, AIR, bid_ref(S.rfq_id, AIR))
    assert mail["to"] == AIR.email
    assert "[BID RFQ-7-COBALT-SKYLIFT]" in mail["subject"]
    assert "Chargeable weight: 321.0 kg" in mail["body"]  # 1.92 m3 x 167 = 320.64


def test_reply_with_total_and_range():
    q = parse_bid_reply("Dear team,\nour all-in price is EUR 1,234.50.\nTransit 3-4 days, valid until 30 Nov.\n")
    assert (q.total, q.currency, q.transit_days, q.confidence) == (D("1234.50"), "EUR", 4, "high")


def test_reply_breakdown_picks_total():
    q = parse_bid_reply("Freight: 1.800,00 EUR\nFuel: 300,00 EUR\nTotal: 2.100,00 EUR\nTransit: 2 days")
    assert q.total == D("2100.00") and q.transit_days == 2


def test_reply_per_kg_only():
    q = parse_bid_reply("We can offer EUR 2.10/kg all-in, 3 days.")
    assert q.total is None and q.per_kg == D("2.10")
    sent = BidTracker().record_sent({"id": 1}, "RFQ-7", AIR, "R")
    opt = bid_option(S, sent, q)
    assert opt.total == D("674.10")  # 2.10 x 321.0 kg


def test_reply_ignores_our_quoted_request():
    q = parse_bid_reply("Price EUR 900\n\nOn Sat, WRATHOFCODE wrote:\n> Gross weight: 300 kg, EUR 5000")
    assert q.total == D("900")


def test_decline():
    q = parse_bid_reply("Sorry, we have no capacity this week.")
    assert q.declined and bid_option(S, BidTracker().record_sent({"id": 2}, "RFQ-7", AIR, "R"), q) is None


def test_tracker_matches_by_thread_then_subject():
    tr = BidTracker()
    tr.record_sent({"id": 77}, "RFQ-7", AIR, "RFQ-7-COBALT-SKYLIFT")
    tr.record_sent({"id": 78}, "RFQ-7", TRUCK, "RFQ-7-TAUNUSFR")
    assert tr.match({"in_reply_to": 77}).carrier is AIR
    assert tr.match({"references": [5, 78]}).carrier is TRUCK
    tr2 = BidTracker()
    tr2.record_sent({"id": 9}, "RFQ-7", AIR, "RFQ-7-COBALT-SKYLIFT")
    assert tr2.match({"subject": "Re: [BID RFQ-7-COBALT-SKYLIFT] quote"}).carrier is AIR
    assert tr2.waiting("RFQ-7") == []


def test_trucker_reply_is_a_pickup_leg():
    sent = BidTracker().record_sent({"id": 3}, "RFQ-7", TRUCK, "R")
    opt = bid_option(S, sent, parse_bid_reply("Pickup price: 145,00 EUR"))
    assert opt.leg == "pickup" and opt.total == D("145.00")
