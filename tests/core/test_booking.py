from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx

from core.agents.booking import BookingAgent, is_acceptance
from core.agents.directory import load_directory
from core.agents.mailbox import parse_mail
from core.contracts import Mail, MailKind, OutgoingMail
from core.store import Store
from tests.core.test_llm import SETTINGS

BASE = "https://portal.test"
KIT = Path(__file__).parent / "fixtures" / "kit"


class FakeMailbox:
    def __init__(self) -> None:
        self.sent: list[OutgoingMail] = []

    async def send(self, mail: OutgoingMail) -> Mail:
        self.sent.append(mail)
        return parse_mail(
            {
                "id": 9000 + len(self.sent),
                "from": "wrathofcode@hackloop.mail",
                "to": mail.to,
                "subject": mail.subject,
                "body": mail.body,
                "in_reply_to": mail.in_reply_to,
                "references": [],
                "received_at": datetime.now(UTC).isoformat(),
                "attachments": [],
            }
        )


class Orch:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.mailbox = FakeMailbox()
        self.events: list[tuple] = []

    def clock(self) -> datetime:
        return datetime.now(UTC)

    def emit(self, agent, step, status, message, rfq_id=None, **kw) -> None:
        self.events.append((agent.value, step, status.value, message))


def quoted(store: Store, rate_id: str | None = "R-abcdefgh1234") -> None:
    store.upsert_rfq("276", "276", "lindqvist-medtech@hackloop.mail", "Fastest air freight to ORD",
                     datetime.now(UTC), "QUOTED")
    store.update_rfq(
        "276",
        status="QUOTED",
        carrier="Meridian Freightways",
        total="3228.87",
        currency="EUR",
        rate_id=rate_id,
        quoted_at=time.time(),
        breakdown_json=json.dumps({"transit_days": 1, "origin": "CGN", "destination": "ORD",
                                   "carrier_code": "MF", "source": "portal"}),
    )


def yes(body: str = "Thank you for your offer. That works for us, please go ahead and book it.\n\nSara"):
    return parse_mail(
        {
            "id": 404,
            "from": "lindqvist-medtech@hackloop.mail",
            "to": "wrathofcode@hackloop.mail",
            "subject": "Re: Fastest air freight to ORD",
            "body": body,
            "in_reply_to": 400,
            "references": [276, 400],
            "received_at": datetime.now(UTC).isoformat(),
            "attachments": [],
        }
    )


def agent(client: httpx.AsyncClient) -> BookingAgent:
    settings = replace(SETTINGS, base_url=BASE, dry_run=False, kill_switch=False)
    return BookingAgent(client, settings, portal=None, directory=load_directory(KIT))


def test_acceptance_words():
    assert is_acceptance("Thank you for your offer. That works for us, please go ahead and book it.")
    assert is_acceptance("Ja, bitte buchen.")
    assert not is_acceptance("Thank you for your offer, but your price is too high for us, so we will not go ahead with it.")
    assert not is_acceptance("Can you do it cheaper?")


@respx.mock
async def test_yes_books_rate_and_confirms_once(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.db")
    quoted(store)
    route = respx.post(f"{BASE}/v1/portal/bookings").respond(
        201,
        json={"booking_reference": "BK-AB12CD34", "team_reference": "WOC-276", "rate_id": "R-abcdefgh1234",
              "airline": "Meridian Freightways", "airline_code": "MF", "price": "3100.00", "currency": "EUR",
              "status": "booked"},
    )
    orch = Orch(store)
    async with httpx.AsyncClient() as client:
        booker = agent(client)
        await booker.handle(orch, yes(), MailKind.FOLLOW_UP)
        await booker.handle(orch, yes(), MailKind.FOLLOW_UP)
    assert route.call_count == 1
    assert json.loads(route.calls.last.request.content) == {"rate_id": "R-abcdefgh1234", "team_reference": "WOC-276"}
    assert len(orch.mailbox.sent) == 1
    confirmation = orch.mailbox.sent[0]
    assert confirmation.in_reply_to == 404 and confirmation.to == "lindqvist-medtech@hackloop.mail"
    assert confirmation.body.startswith("Hi Sara,") and "BK-AB12CD34" in confirmation.body
    row = store._conn.execute("SELECT status, booking_reference, eta FROM bookings").fetchone()
    assert row[0] == "booked" and row[1] == "BK-AB12CD34" and row[2]
    assert store._conn.execute("SELECT status FROM rfqs WHERE id='276'").fetchone()[0] == "BOOKED"
    store.close()


async def test_no_does_not_book(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.db")
    quoted(store)
    orch = Orch(store)
    async with httpx.AsyncClient() as client:
        await agent(client).handle(orch, yes("Your price is too high, we will not go ahead."), MailKind.FOLLOW_UP)
    assert orch.mailbox.sent == []
    assert store._conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0
    store.close()


async def test_airline_confirmation_marks_booking(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.db")
    with store._write() as conn:
        conn.execute(
            "INSERT INTO bookings (rfq_id, thread_id, team_reference, booking_reference, status) "
            "VALUES ('276', '276', 'WOC-276', 'BK-AB12CD34', 'booked')"
        )
    orch = Orch(store)
    mail = parse_mail({"id": 500, "from": "meridian-freightways@hackloop.mail", "to": "wrathofcode@hackloop.mail",
                       "subject": "Booking BK-AB12CD34 confirmed", "body": "Confirmed.", "in_reply_to": None,
                       "references": [], "received_at": datetime.now(UTC).isoformat(), "attachments": []})
    async with httpx.AsyncClient() as client:
        await agent(client).handle(orch, mail, MailKind.BOOKING_CONFIRMATION)
    assert store._conn.execute("SELECT status FROM bookings").fetchone()[0] == "confirmed"
    store.close()
