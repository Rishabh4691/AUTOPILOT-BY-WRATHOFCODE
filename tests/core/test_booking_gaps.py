from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from types import SimpleNamespace
import respx

from core.agents.booking import BookingAgent, is_acceptance, quote_from_mail, record_sent_quote
from core.agents.directory import load_directory
from core.agents.mailbox import parse_mail
from core.contracts import MailKind
from core.store import Store
from tests.core.test_booking import BASE, KIT, Orch, quoted, yes
from tests.core.test_llm import SETTINGS

OUR_QUOTE = (
    "Hi Sara,\n\nfor your spare parts from Cologne to Chicago I would go with Meridian Freightways, "
    "the fastest choice, arriving around Thu 26 Nov. The all-in price is EUR 3,228.87, including the "
    "truck pickup, fuel and security. A yes is all I need to book it. Our reference is WOC-276.\n\nCheers,\nLena"
)
BOOKED = {
    "booking_reference": "BK-NEW00001",
    "team_reference": "WOC-276",
    "airline": "Meridian Freightways",
    "price": "3228.87",
    "currency": "EUR",
    "status": "booked",
}


class Outbound:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send_new(self, to: str, subject: str, body: str) -> int:
        self.sent.append((to, subject, body))
        return 1


def booker(client: httpx.AsyncClient, outbound=None) -> BookingAgent:
    settings = replace(SETTINGS, base_url=BASE, dry_run=False, kill_switch=False)
    agent = BookingAgent(client, settings, portal=None, directory=load_directory(KIT), outbound=outbound)
    agent.retry_after_s = 0
    return agent


def our_mail(body: str = OUR_QUOTE, sender: str = SETTINGS.our_address):
    return parse_mail(
        {
            "id": 400,
            "from": sender,
            "to": "lindqvist-medtech@hackloop.mail",
            "subject": "Re: Fastest air freight to ORD",
            "body": body,
            "in_reply_to": 276,
            "references": [276],
            "received_at": datetime.now(UTC).isoformat(),
            "attachments": [],
        }
    )


@pytest.mark.parametrize(
    "text",
    [
        "好的，请帮我们订舱。",
        "はい、予約をお願いします。",
        "네, 예약해 주세요.",
        "Да, бронируйте, пожалуйста.",
        "Evet, lütfen rezervasyon yapın.",
        "نعم، يرجى الحجز",
        "Sim, pode reservar.",
        "Ja, graag boeken.",
    ],
)
def test_yes_in_more_languages(text):
    assert is_acceptance(text)


@pytest.mark.parametrize(
    "text",
    [
        "不需要了，谢谢。",
        "谢谢您的报价，太贵了，我们暂不考虑。",
        "いいえ、今回は見送ります。",
        "Нет, спасибо, дорого.",
        "Hayır, teşekkürler.",
        "Thank you for your offer. That seems too low to be right, so we will not go ahead with it.",
        "Thanks, could you also check a faster option?",
        "Je ne sais pas encore, pouvez-vous vérifier un autre départ ?",
    ],
)
def test_no_and_questions_stay_unbooked(text):
    assert not is_acceptance(text)


def test_quote_read_back_from_our_mail():
    airlines = [c.name for c in load_directory(KIT).airlines()]
    assert quote_from_mail(OUR_QUOTE, airlines) == ("Meridian Freightways", "3228.87", "EUR")
    assert quote_from_mail("Thanks, we will check and come back.", airlines) is None


@respx.mock
async def test_yes_on_a_quote_sent_outside_the_bot_gets_booked(tmp_path):
    store = Store(tmp_path / "app.db")
    orch = Orch(store)
    orch.mailbox.stored[400] = our_mail()
    # The live bot can read the customer's original request (rounds 103/104: without the airports
    # the airline refused the booking mail, so an empty route is no longer sent).
    orch.mailbox.stored[276] = our_mail()

    class Reader:
        async def extract(self, mail):
            return SimpleNamespace(origin="CGN", destination="ORD"), None

    orch.extractor = Reader()
    outbound = Outbound()
    async with httpx.AsyncClient() as client:
        await booker(client, outbound).handle(orch, yes(), MailKind.FOLLOW_UP)
    row = store._conn.execute("SELECT carrier, total, status FROM rfqs WHERE id='276'").fetchone()
    assert row[0] == "Meridian Freightways" and str(row[1]) == "3228.87" and row[2] == "BOOKED"
    assert outbound.sent and outbound.sent[0][0] == "meridian-freightways@hackloop.mail"
    assert "WOC-276" in outbound.sent[0][2] and "Route: CGN to ORD." in outbound.sent[0][2]
    assert len(orch.mailbox.sent) == 1 and orch.mailbox.sent[0].in_reply_to == 404
    store.close()


async def test_yes_replying_to_someone_else_is_not_adopted(tmp_path):
    store = Store(tmp_path / "app.db")
    orch = Orch(store)
    orch.mailbox.stored[400] = our_mail(sender="other-team@hackloop.mail")
    async with httpx.AsyncClient() as client:
        await booker(client, Outbound()).handle(orch, yes(), MailKind.FOLLOW_UP)
    assert store._conn.execute("SELECT COUNT(*) FROM rfqs").fetchone()[0] == 0
    assert orch.mailbox.sent == []
    store.close()


@respx.mock
async def test_record_sent_quote_then_chinese_yes_books_by_portal(tmp_path):
    store = Store(tmp_path / "app.db")
    record_sent_quote(
        store, 276, 276, "lindqvist-medtech@hackloop.mail", "Re: quote", "Meridian Freightways",
        "3228.87", "EUR", "R-abcdefgh1234", OUR_QUOTE,
    )
    route = respx.post(f"{BASE}/v1/portal/bookings").respond(201, json=BOOKED)
    orch = Orch(store)
    async with httpx.AsyncClient() as client:
        await booker(client).handle(orch, yes("好的，请帮我们订舱。\n\nSara"), MailKind.FOLLOW_UP)
    assert route.call_count == 1
    assert store._conn.execute("SELECT booking_reference FROM bookings").fetchone()[0] == "BK-NEW00001"
    store.close()


@respx.mock
async def test_failed_booking_is_retried_once(tmp_path):
    store = Store(tmp_path / "app.db")
    quoted(store)
    route = respx.post(f"{BASE}/v1/portal/bookings").mock(
        side_effect=[httpx.Response(503), httpx.Response(201, json=BOOKED)]
    )
    orch = Orch(store)
    async with httpx.AsyncClient() as client:
        await booker(client).handle(orch, yes(), MailKind.FOLLOW_UP)
    assert route.call_count == 2
    assert store._conn.execute("SELECT status FROM rfqs WHERE id='276'").fetchone()[0] == "BOOKED"
    store.close()


async def test_recheck_skips_replies_already_read_as_no(tmp_path):
    store = Store(tmp_path / "app.db")
    quoted(store)
    no = yes("Your price is too high, we will not go ahead.")
    store.mark_seen(no, MailKind.FOLLOW_UP)
    orch = Orch(store)
    orch.mailbox.stored[no.id] = no
    reads = []
    original = orch.mailbox.read_one

    async def counting(message_id):
        reads.append(message_id)
        return await original(message_id)

    orch.mailbox.read_one = counting
    async with httpx.AsyncClient() as client:
        agent = booker(client)
        await agent.handle(orch, no, MailKind.FOLLOW_UP)
        await agent.recover(orch)
        await agent.recover(orch)
    assert reads == []
    store.close()


def test_manual_script_records_its_quote():
    source = open("scripts/manual_quote.py", encoding="utf-8").read()
    assert "record_sent_quote" in source


@pytest.mark.parametrize("language", ["zh", "ja", "ko", "ru", "tr", "ar", "pt", "nl"])
def test_confirmation_in_the_customer_language(language):
    from core.agents.booking import CONFIRM, confirmation_body
    from tests.core.test_booking import CONFIRMED

    body = confirmation_body(CONFIRMED, {"total": "3228.87", "currency": "EUR"}, language, "Sara", "Lena", "WOC")
    assert language in CONFIRM
    assert "BK-AB12CD34" in body and "WOC-276" in body and "Sara" in body
    assert " to " not in body
