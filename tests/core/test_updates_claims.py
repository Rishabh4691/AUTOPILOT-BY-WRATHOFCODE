from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from test_orchestrator import KIT, drain, harness, mail

from core import runtime_settings
from core.agents.claims import ClaimsAgent, kind_of
from core.agents.directory import load_directory
from core.agents.updates import ShipmentUpdates


@pytest.fixture(autouse=True)
def settings_file(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_SETTINGS_PATH", str(tmp_path / "settings.json"))
    runtime_settings._cache.update(mtime=None, data=dict(runtime_settings.DEFAULTS))


def booked(store, rfq_id="276", eta="2026-11-30", ref="BK-AB12CD34", hours_ago=2, body="Hi Sara,\n\nThanks for the details."):
    store.upsert_rfq(rfq_id, rfq_id, "lindqvist-medtech@hackloop.mail", "Fastest air freight to ORD",
                     datetime.now(UTC) - timedelta(hours=hours_ago), "BOOKED")
    store.update_rfq(rfq_id, status="BOOKED", carrier="Lumen Air Cargo", email_body=body)
    with store._write() as conn:
        conn.execute(
            "INSERT INTO bookings (rfq_id, thread_id, team_reference, booking_reference, carrier, origin, destination, eta, status, booked_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rfq_id, rfq_id, f"WOC-{rfq_id}", ref, "Lumen Air Cargo", "FRA", "ORD", eta, "booked", 1.0),
        )


async def test_updates_stay_off_until_the_switch_is_on(tmp_path: Path):
    h = harness(tmp_path)
    booked(h.store)
    agent = ShipmentUpdates(today=lambda: date(2026, 11, 22))
    assert await agent.tick(h.orchestrator) == 0
    runtime_settings.save({"daily_updates": True})
    assert await agent.tick(h.orchestrator) == 1
    sent = h.mailbox.sent[0]
    assert sent.to == "lindqvist-medtech@hackloop.mail" and sent.in_reply_to == 276
    assert sent.body.startswith("Hi Sara,") and "BK-AB12CD34" in sent.body and "WOC-276" in sent.body
    assert await agent.tick(h.orchestrator) == 0, "one update per 24 hours"


async def test_arrival_note_moves_the_shipment_to_delivered(tmp_path: Path):
    h = harness(tmp_path)
    booked(h.store, eta="2026-11-21")
    runtime_settings.save({"daily_updates": True})
    agent = ShipmentUpdates(today=lambda: date(2026, 11, 22))
    assert await agent.tick(h.orchestrator) == 1
    assert "was due at" in h.mailbox.sent[0].body and "missing or damaged" in h.mailbox.sent[0].body
    row = h.store._conn.execute("SELECT delivered_at FROM shipment_updates WHERE rfq_id='276'").fetchone()
    assert row[0] is not None
    assert await agent.tick(h.orchestrator) == 0, "a delivered shipment gets no more mail"


async def test_no_updates_right_after_a_new_request(tmp_path: Path):
    h = harness(tmp_path)
    booked(h.store, hours_ago=0)
    runtime_settings.save({"daily_updates": True})
    assert await ShipmentUpdates().tick(h.orchestrator) == 0


async def test_updates_follow_the_customer_language(tmp_path: Path):
    h = harness(tmp_path)
    booked(h.store, body="Hallo Jonas,\n\ndanke für die Anfrage, unsere Referenz ist WOC-276. Viele Grüße")
    runtime_settings.save({"daily_updates": True})
    await ShipmentUpdates(today=lambda: date(2026, 11, 22)).tick(h.orchestrator)
    assert h.mailbox.sent[0].body.startswith("Hallo Jonas,")


async def test_damaged_complaint_files_a_claim_with_the_airline_and_confirms(tmp_path: Path):
    h = harness(tmp_path)
    booked(h.store)
    airline_mails = []

    class Outbound:
        async def send_new(self, to, subject, body):
            airline_mails.append((to, subject, body))
            return 1

    h.orchestrator.claims = ClaimsAgent(load_directory(KIT), outbound=Outbound())
    complaint = mail(900, sender="lindqvist-medtech@hackloop.mail", subject="Re: Fastest air freight to ORD",
                     body="Two boxes arrived damaged in Chicago. Please help.", in_reply_to=276, references=[276])
    h.orchestrator.route(complaint)
    await drain(h)
    (to, subject, body), = airline_mails
    assert to == "lumen-air-cargo@hackloop.mail" and "CLM-276" in subject and "BK-AB12CD34" in body
    assert "arrived damaged" in body
    ack = h.mailbox.sent[0]
    assert ack.to == "lindqvist-medtech@hackloop.mail" and ack.in_reply_to == 900 and "CLM-276" in ack.body
    claim = h.store._conn.execute("SELECT kind, status FROM claims").fetchone()
    assert claim == ("damaged", "filed")


async def test_ordinary_reply_files_no_claim(tmp_path: Path):
    h = harness(tmp_path)
    booked(h.store)
    h.orchestrator.claims = ClaimsAgent(load_directory(KIT))
    h.orchestrator.route(mail(901, sender="lindqvist-medtech@hackloop.mail", subject="Re: Fastest air freight to ORD",
                              body="Thanks for booking, please make sure nothing gets damaged.", in_reply_to=276, references=[276]))
    await drain(h)
    assert not [m for m in h.mailbox.sent if "CLM-" in (m.subject + m.body)]


@pytest.mark.parametrize("text, kind", [
    ("Two boxes arrived damaged, please help.", "damaged"),
    ("The shipment never arrived in Chicago.", "lost"),
    ("Die Sendung ist nicht angekommen.", "lost"),
    ("Il collo è arrivato danneggiato", "damaged"),
    ("Es fehlt noch die Rechnung.", None),
    ("la rotta più veloce per favore", None),
    ("Falta información sobre el envío", None),
])
def test_claim_detection(text: str, kind: str | None):
    assert kind_of(text) == kind


def test_model_switch_only_accepts_known_models():
    assert runtime_settings.writer_model() is None
    runtime_settings.save({"writer_model": "gpt-4.1"})
    assert runtime_settings.writer_model() == "gpt-4.1"
    with pytest.raises(ValueError):
        runtime_settings.save({"writer_model": "gpt-9"})
