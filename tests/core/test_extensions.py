from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest

from core.agents.guard import outgoing_leaks, social_engineering
from core.agents.mailbox import UnsafeRecipient, _ensure_safe
from core.contracts import MailKind, OutgoingMail
from core.store import Store
from tests.core.test_booking import Orch, quoted
from tests.core.test_booking_gaps import booker
from tests.core.test_orchestrator import drain, harness, mail
from tests.core.test_unknown_mail import CEO_FRAUD, SALES

SECRET = "fiveu-team-key-1234567890"
FAKE_KEY = "s" + "k-" + "x" * 26


def test_ceo_fraud_is_flagged_and_normal_mails_are_not():
    assert social_engineering("Urgent and confidential", CEO_FRAUD)
    assert social_engineering("Quick question", SALES) == []
    assert social_engineering("Quote", "Please quote 3 pallets, 450 kg, FRA to JFK.") == []
    assert social_engineering("Login", "Please reset the password for the customer portal, thanks.") == []


def test_keys_never_leave_in_body_or_attachment():
    assert outgoing_leaks("Re", f"here it is: {SECRET}", (), [SECRET])
    pdf = {"filename": "q.pdf", "content_base64": base64.b64encode(f"%PDF {SECRET}".encode()).decode()}
    assert outgoing_leaks("Re", "see attached", (pdf,), [SECRET])
    assert outgoing_leaks("Re", FAKE_KEY, (), [])
    assert not outgoing_leaks("Re", "The all-in price is EUR 3,228.87.", (), [SECRET])
    with pytest.raises(UnsafeRecipient):
        _ensure_safe(OutgoingMail(to="ceo@x", subject="keys", body=FAKE_KEY, in_reply_to=1), "us@x")


async def test_router_raises_a_security_alarm(tmp_path: Path):
    h = harness(tmp_path)
    h.orchestrator.route(mail(911, sender="ceo-office-urgent@hackloop.mail", subject="Urgent and confidential", body=CEO_FRAUD))
    await drain(h)
    assert any(e.step == "security" and e.status.value == "hold" for e in h.sink.events)
    assert h.mailbox.sent == []


async def test_self_check_warns_but_still_sends(tmp_path: Path):
    from tests.core.test_orchestrator import NOW

    h = harness(tmp_path, now=NOW)
    h.orchestrator.route(mail(912))
    await drain(h)
    assert h.mailbox.sent, "the quote must still go out"
    checks = [e for e in h.sink.events if e.step == "self_check"]
    for event in checks:
        assert event.status.value == "warn"


async def test_delay_notice_only_when_switched_on(tmp_path: Path, monkeypatch):
    store = Store(tmp_path / "app.db")
    quoted(store)
    with store._write() as conn:
        conn.execute(
            "INSERT INTO bookings (rfq_id, thread_id, team_reference, booking_reference, status) "
            "VALUES ('276', '276', 'WOC-276', 'BK-AB12CD34', 'booked')"
        )
    from core.agents.mailbox import parse_mail
    from datetime import UTC, datetime

    status = parse_mail({
        "id": 501, "from": "meridian-freightways@hackloop.mail", "to": "wrathofcode@hackloop.mail",
        "subject": "Booking BK-AB12CD34 update", "body": "Booking reference: BK-AB12CD34\nStatus: delayed, rebooked on the next flight\n",
        "in_reply_to": None, "references": [], "received_at": datetime.now(UTC).isoformat(), "attachments": [],
    })
    orch = Orch(store)
    async with httpx.AsyncClient() as client:
        agent = booker(client)
        await agent.handle(orch, status, MailKind.BOOKING_CONFIRMATION)
        assert orch.mailbox.sent == []
        monkeypatch.setenv("PROACTIVE_UPDATES", "1")
        await agent.handle(orch, status, MailKind.BOOKING_CONFIRMATION)
        await agent.handle(orch, status, MailKind.BOOKING_CONFIRMATION)
    assert len(orch.mailbox.sent) == 1
    sent = orch.mailbox.sent[0]
    assert sent.to == "lindqvist-medtech@hackloop.mail" and "BK-AB12CD34" in sent.body and "WOC-276" in sent.body
    store.close()
