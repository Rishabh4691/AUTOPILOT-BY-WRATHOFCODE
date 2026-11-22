from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from core.agents.mailbox import parse_mail
from core.agents.tracking import TrackingAgent, match
from core.store import Store
from tests.core.test_booking import Orch

BOOKED = {
    "rfq_id": "276",
    "thread_id": "276",
    "customer": "lindqvist-medtech@hackloop.mail",
    "booking_reference": "BK-AB12CD34",
    "team_reference": "WOC-276",
    "carrier": "Meridian Freightways",
    "origin": "CGN",
    "destination": "ORD",
    "transit_days": 1,
    "ready_date": "2026-11-25",
    "eta": "2026-11-26",
    "status": "booked",
}
OTHER = {
    **BOOKED,
    "rfq_id": "432",
    "thread_id": "432",
    "customer": "sonnberg-roesterei@hackloop.mail",
    "booking_reference": "BK-ZZ99YY88",
    "team_reference": "WOC-432",
    "carrier": "Solace Air Cargo",
    "origin": "FRA",
    "destination": "JFK",
    "eta": "2026-11-27",
}


def question(i: int, subject: str, body: str):
    return parse_mail(
        {
            "id": i,
            "from": "tracking@hackloop.mail",
            "to": "wrathofcode@hackloop.mail",
            "subject": subject,
            "body": body,
            "in_reply_to": None,
            "references": [],
            "received_at": datetime.now(UTC).isoformat(),
            "attachments": [],
        }
    )


def store_with(tmp_path: Path, *rows: dict) -> Store:
    store = Store(tmp_path / "app.db")
    with store._write() as conn:
        for r in rows:
            cols = ", ".join(r)
            conn.execute(
                f"INSERT INTO bookings ({cols}) VALUES ({', '.join('?' for _ in r)})",
                tuple(r.values()),
            )
    return store


def test_match_by_reference_company_and_route():
    rows = [BOOKED, OTHER]
    assert match("Where is BK-AB12CD34?", rows)["rfq_id"] == "276"
    assert match("Status of our shipment WOC-432 please", rows)["rfq_id"] == "432"
    assert match("Any news on the Lindqvist Medtech shipment to Chicago?", rows)["rfq_id"] == "276"
    assert match("Where is our FRA-JFK shipment?", rows)["rfq_id"] == "432"
    assert match("Where is my parcel?", rows) is None


async def test_answer_once_with_status_and_eta(tmp_path: Path) -> None:
    store = store_with(tmp_path, BOOKED, OTHER)
    orch = Orch(store)
    agent = TrackingAgent()
    q = question(
        700, "Tracking BK-AB12CD34", "Hello, where is shipment BK-AB12CD34 and when will it arrive?"
    )
    await agent.handle(orch, q)
    await agent.handle(orch, q)
    assert len(orch.mailbox.sent) == 1
    reply = orch.mailbox.sent[0]
    assert reply.in_reply_to == 700 and reply.to == "tracking@hackloop.mail"
    assert "BK-AB12CD34" in reply.body and "Meridian Freightways" in reply.body
    assert "Thu 26 Nov" in reply.body and "Cologne (CGN) to Chicago (ORD)" in reply.body
    assert "2026-" not in reply.body and "→" not in reply.body
    store.close()


async def test_unknown_question_goes_to_a_person(tmp_path: Path) -> None:
    store = store_with(tmp_path, BOOKED)
    orch = Orch(store)
    await TrackingAgent().handle(orch, question(701, "Status", "Where is my parcel?"))
    assert orch.mailbox.sent == []
    assert orch.events[-1][2] == "hold"
    store.close()


def test_answer_repeats_the_airline_status():
    text = TrackingAgent().answer(
        {**BOOKED, "status": "confirmed", "note": "booked and ready to ship"}, "en"
    )
    assert "Latest status from Meridian Freightways: booked and ready to ship." in text


def test_answer_greets_asker_uses_our_reference_and_no_zero_days():
    agent = TrackingAgent()
    restarted = {**BOOKED, "transit_days": 0, "price": "3228.87", "currency": "EUR"}
    text = agent.answer(restarted, "en", "Klaus")
    assert text.startswith("Hi Klaus,\n\nHere's the latest on our reference WOC-276")
    assert "0 days" not in text and "EUR 3,228.87" in text
    assert "Cologne (CGN) to Chicago (ORD)" in text and "→" not in text
    assert "Wed 25 Nov" in text and "Thu 26 Nov" in text
    timed = agent.answer({**BOOKED, "transit_days": 1, "eta": "2026-11-27"}, "en")
    assert timed.startswith("Hi,\n\n") and "leaving Wed 25 Nov" in timed and "Fri 27 Nov" in timed


def test_asker_name_comes_from_the_signature():
    from core.agents.tracking import asker_name

    assert asker_name("Hi, where is WOC-276?\n\nThanks,\nKlaus") == "Klaus"
    assert asker_name("Where is BK-AB12CD34?") == ""


def test_match_by_weight_lane_and_date_without_company():
    rows = [
        {
            **BOOKED,
            "weight_kg": 486,
            "origin": "MUC",
            "destination": "CAI",
            "ready_date": "2026-11-24",
        },
        OTHER,
    ]
    hit = match("Where is our shipment MUC to CAI, 486 kg, ready 2026-11-24?", rows)
    assert hit is not None and hit["rfq_id"] == "276"
