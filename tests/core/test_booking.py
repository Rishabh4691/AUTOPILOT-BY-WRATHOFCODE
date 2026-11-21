from __future__ import annotations

import json
import re
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
        self.stored: dict[int, Mail] = {}

    async def read_one(self, message_id: int) -> Mail:
        return self.stored[message_id]

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
    store.upsert_rfq(
        "276",
        "276",
        "lindqvist-medtech@hackloop.mail",
        "Fastest air freight to ORD",
        datetime.now(UTC),
        "QUOTED",
    )
    store.update_rfq(
        "276",
        status="QUOTED",
        carrier="Meridian Freightways",
        total="3228.87",
        currency="EUR",
        rate_id=rate_id,
        quoted_at=time.time(),
        breakdown_json=json.dumps(
            {
                "transit_days": 1,
                "origin": "CGN",
                "destination": "ORD",
                "carrier_code": "MF",
                "source": "portal",
            }
        ),
    )


def yes(
    body: str = "Thank you for your offer. That works for us, please go ahead and book it.\n\nSara",
):
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
    assert is_acceptance(
        "Thank you for your offer. That works for us, please go ahead and book it."
    )
    assert is_acceptance("Ja, bitte buchen.")
    assert not is_acceptance(
        "Thank you for your offer, but your price is too high for us, so we will not go ahead with it."
    )
    assert not is_acceptance("Can you do it cheaper?")


@respx.mock
async def test_yes_books_rate_and_confirms_once(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.db")
    quoted(store)
    route = respx.post(f"{BASE}/v1/portal/bookings").respond(
        201,
        json={
            "booking_reference": "BK-AB12CD34",
            "team_reference": "WOC-276",
            "rate_id": "R-abcdefgh1234",
            "airline": "Meridian Freightways",
            "airline_code": "MF",
            "price": "3100.00",
            "currency": "EUR",
            "status": "booked",
        },
    )
    orch = Orch(store)
    async with httpx.AsyncClient() as client:
        booker = agent(client)
        await booker.handle(orch, yes(), MailKind.FOLLOW_UP)
        await booker.handle(orch, yes(), MailKind.FOLLOW_UP)
    assert route.call_count == 1
    assert json.loads(route.calls.last.request.content) == {
        "rate_id": "R-abcdefgh1234",
        "team_reference": "WOC-276",
    }
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
        await agent(client).handle(
            orch, yes("Your price is too high, we will not go ahead."), MailKind.FOLLOW_UP
        )
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
    mail = parse_mail(
        {
            "id": 500,
            "from": "meridian-freightways@hackloop.mail",
            "to": "wrathofcode@hackloop.mail",
            "subject": "Booking BK-AB12CD34 confirmed",
            "body": "Booking reference: BK-AB12CD34\nStatus: booked and ready to ship\n",
            "in_reply_to": None,
            "references": [],
            "received_at": datetime.now(UTC).isoformat(),
            "attachments": [],
        }
    )
    async with httpx.AsyncClient() as client:
        await agent(client).handle(orch, mail, MailKind.BOOKING_CONFIRMATION)
    assert tuple(store._conn.execute("SELECT status, note FROM bookings").fetchone()) == (
        "confirmed",
        "booked and ready to ship",
    )
    store.close()


@respx.mock
async def test_recover_books_a_yes_missed_while_the_bot_was_old(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.db")
    quoted(store)
    accept = yes()
    store.mark_seen(accept, MailKind.FOLLOW_UP)
    respx.post(f"{BASE}/v1/portal/bookings").respond(
        201,
        json={
            "booking_reference": "BK-REC00001",
            "team_reference": "WOC-276",
            "rate_id": "R-abcdefgh1234",
            "airline": "Meridian Freightways",
            "airline_code": "MF",
            "price": "3228.87",
            "currency": "EUR",
            "status": "booked",
        },
    )
    orch = Orch(store)
    orch.mailbox.stored[accept.id] = accept
    async with httpx.AsyncClient() as client:
        assert await agent(client).recover(orch) == 1
    assert (
        store._conn.execute("SELECT booking_reference FROM bookings").fetchone()[0] == "BK-REC00001"
    )
    assert len(orch.mailbox.sent) == 1
    store.close()


def test_more_ways_to_say_yes():
    for text in [
        "Approved, please proceed.",
        "Agreed.",
        "PO attached, go for it.",
        "We'll take it.",
        "Auftrag erteilt, freigegeben.",
    ]:
        assert is_acceptance(text), text


CONFIRMED = {
    "booking_reference": "BK-AB12CD34",
    "team_reference": "WOC-276",
    "carrier": "Meridian Freightways",
    "origin": "CGN",
    "destination": "ORD",
    "transit_days": 2,
    "eta": "2026-12-04",
}


def test_confirmation_uses_our_reference_price_format_and_short_dates():
    from core.agents.booking import confirmation_body

    rfq = {"total": "3228.87", "currency": "EUR"}
    body = confirmation_body(CONFIRMED, rfq, "en", "Sara", "Lena", "WRATHOFCODE Air Freight")
    assert body.startswith("Hi Sara,\n\nGood news")
    assert "our reference WOC-276" in body and "your reference" not in body.lower()
    assert "Fri 4 Dec" in body and "2026-12-04" not in body
    assert "EUR 3,228.87" in body and "2 days in transit" in body
    assert not re.search(r"[.!?]\s+[a-z]", body)
    restarted = confirmation_body({**CONFIRMED, "transit_days": 0}, rfq, "en", "", "Lena", "X")
    assert "0 days" not in restarted and restarted.startswith("Hi there,")
    polish = confirmation_body(CONFIRMED, rfq, "pl", "", "Lena", "X")
    assert "Państwa" not in polish and "nasz numer" in polish


def test_booking_reuses_the_quoted_arrival():
    from datetime import date

    from core.agents.booking import booking_eta
    from mail.writer import arrival_date

    assert booking_eta({"arrival": "2026-12-01", "transit_days": 0}) == "2026-12-01"
    today = date(2026, 11, 21)
    quoted = arrival_date("2026-11-28", 2, today).isoformat()
    recomputed = booking_eta({"ready_date": "2026-11-28", "transit_days": 2}, today)
    assert recomputed == quoted == "2026-12-01"


@respx.mock
async def test_old_rate_id_is_still_tried_on_the_portal_first(tmp_path: Path) -> None:
    store = Store(tmp_path / "app.db")
    quoted(store, rate_id="R-M2SDYd0xvjzvCzMf")
    store.update_rfq("276", quoted_at=time.time() - 3600)
    route = respx.post(f"{BASE}/v1/portal/bookings").respond(
        201,
        json={
            "booking_reference": "BK-OLDRATE1",
            "team_reference": "WOC-276",
            "rate_id": "R-M2SDYd0xvjzvCzMf",
            "airline": "Meridian Freightways",
            "airline_code": "MF",
            "price": "3228.87",
            "currency": "EUR",
            "status": "booked",
        },
    )
    orch = Orch(store)
    async with httpx.AsyncClient() as client:
        await agent(client).handle(orch, yes(), MailKind.FOLLOW_UP)
    assert route.call_count == 1
    assert (
        store._conn.execute("SELECT booking_reference FROM bookings").fetchone()[0] == "BK-OLDRATE1"
    )
    store.close()


def test_bid_reply_keeps_its_rate_reference():
    from core.agents.airline_bids import RATE_REF

    body = "All-in price: 390.45 EUR\nTransit time: 4 days\nPlease quote reference R-M2SDYd0xvjzvCzMf when booking."
    assert RATE_REF.search(body).group(1) == "R-M2SDYd0xvjzvCzMf"
