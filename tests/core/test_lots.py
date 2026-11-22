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


GERMAN = (
    "Hallo,\n\nbitte um Ihr schnellstes Angebot für zwei Sendungen, beide abholbereit am 2026-11-23 bei uns in "
    "65996 Wiesbaden. Bitte organisieren Sie den Lkw zum Flughafen.\n\n"
    "1. GRU (Sao Paulo): 4 Packstücke, 1281 kg brutto, 3,76 cbm\n"
    "2. TLV (Tel Aviv): 1 Packstück, 1812 kg brutto, 5,75 cbm\n\n"
    "Bitte jeweils einen eigenen All-in-Preis in EUR.\n\nViele Grüße\nPetra Hofmann"
)


async def test_reply_is_in_the_customer_language(tmp_path: Path):
    h = harness(tmp_path, now=NOW)
    h.orchestrator.route(mail(25800, subject="Luftfrachtanfrage GRU und TLV", body=GERMAN))
    await drain(h)
    body = h.mailbox.sent[0].body
    assert body.startswith("Hallo Petra,") and body.count("All-in-Preis") == 2 and "Viele Grüße" in body


async def test_yes_books_every_shipment_and_confirms_once(tmp_path: Path):
    import httpx
    import respx

    from core.agents.mailbox import parse_mail
    from core.contracts import MailKind
    from tests.core.test_booking import BASE
    from tests.core.test_booking_gaps import booker

    h = harness(tmp_path, now=NOW)
    h.orchestrator.route(mail(25799, subject="Air freight quote request: GRU and TLV", body=ROUND89))
    await drain(h)
    rows = h.store._conn.execute("SELECT id, status FROM rfqs WHERE id IN ('257991','257992') ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("257991", "QUOTED"), ("257992", "QUOTED")]
    with h.store._write() as conn:
        conn.execute("UPDATE rfqs SET carrier='Meridian Freightways', rate_id='R-lot0000001' WHERE id='257991'")
        conn.execute("UPDATE rfqs SET carrier='Meridian Freightways', rate_id='R-lot0000002' WHERE id='257992'")
    yes = parse_mail({
        "id": 26100, "from": "buyer@customer.example", "to": "wrathofcode@hackloop.mail",
        "subject": "Re: Air freight quote request: GRU and TLV", "body": "Thanks, that works for us, please book both.",
        "in_reply_to": 10_001, "references": [25799, 10_001], "received_at": NOW.isoformat(), "attachments": [],
    })
    refs = iter(["BK-LOT00001", "BK-LOT00002"])
    with respx.mock:
        route = respx.post(f"{BASE}/v1/portal/bookings").mock(
            side_effect=lambda request: httpx.Response(201, json={"booking_reference": next(refs), "airline": "Meridian Freightways", "status": "booked"})
        )
        async with httpx.AsyncClient() as client:
            agent = booker(client)
            await agent.handle(h.orchestrator, yes, MailKind.FOLLOW_UP)
            await agent.handle(h.orchestrator, yes, MailKind.FOLLOW_UP)
    assert route.call_count == 2
    confirmations = [m for m in h.mailbox.sent if m.in_reply_to == 26100]
    assert len(confirmations) == 1
    assert "BK-LOT00001" in confirmations[0].body and "BK-LOT00002" in confirmations[0].body
    statuses = {r[0]: r[1] for r in h.store._conn.execute("SELECT id, status FROM rfqs WHERE id IN ('257991','257992')")}
    assert statuses == {"257991": "BOOKED", "257992": "BOOKED"}


async def test_partial_yes_books_nothing_and_alarms(tmp_path: Path):
    import httpx

    from core.agents.mailbox import parse_mail
    from core.contracts import MailKind
    from tests.core.test_booking_gaps import booker

    h = harness(tmp_path, now=NOW)
    h.orchestrator.route(mail(25799, subject="Air freight quote request: GRU and TLV", body=ROUND89))
    await drain(h)
    sent_before = len(h.mailbox.sent)
    partial = parse_mail({
        "id": 26101, "from": "buyer@customer.example", "to": "wrathofcode@hackloop.mail",
        "subject": "Re: quote", "body": "Please book shipment 1 only, hold shipment 2 for now.",
        "in_reply_to": 10_001, "references": [25799, 10_001], "received_at": NOW.isoformat(), "attachments": [],
    })
    async with httpx.AsyncClient() as client:
        await booker(client).handle(h.orchestrator, partial, MailKind.FOLLOW_UP)
    assert len(h.mailbox.sent) == sent_before
