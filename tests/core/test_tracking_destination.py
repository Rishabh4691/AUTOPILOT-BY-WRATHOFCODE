from core.agents.tracking import match

ROWS = [
    {"booking_reference": "BK-AMYMXPDB", "rfq_id": "34125", "customer": "sonnberg-roesterei@hackloop.mail",
     "origin": "DUS", "destination": "NBO", "weight_kg": 1061, "ready_date": "2026-11-26",
     "carrier": "Meridian Freightways"},
    {"booking_reference": "BK-RDG6S4DR", "rfq_id": "34770", "customer": "sonnberg-roesterei@hackloop.mail",
     "origin": "DUS", "destination": "JFK", "weight_kg": None, "ready_date": None,
     "carrier": "Fjordline Air Cargo"},
]


def test_round_117_question_about_jfk_gets_the_jfk_booking() -> None:
    q = ("Status of our shipment 47914 to JFK, 1061 kg\nCould you please confirm the current location and "
         "status of the shipment we booked with you for Sonnberg Kaffeeroesterei GmbH, from 47914 to JFK, "
         "with a gross weight of 1061 kg and a ready date of 2026-11-28?")
    assert match(q, ROWS)["booking_reference"] == "BK-RDG6S4DR"


def test_same_customer_nbo_question_still_gets_nbo() -> None:
    q = "Status of our shipment 47914 to NBO, 1061 kg\nSonnberg Kaffeeroesterei GmbH, 47914 to NBO, 1061 kg, ready on 2026-11-26?"
    assert match(q, ROWS)["booking_reference"] == "BK-AMYMXPDB"
