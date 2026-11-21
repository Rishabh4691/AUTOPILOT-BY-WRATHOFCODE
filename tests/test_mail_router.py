import time

import pytest

from mail import kit, router, store
from mail.client import Mail
from mail.config import settings
from mail.router import fresh_text, is_acceptance

CSV = """name,kind,email,serves
Borealis Freight Airways,airline,borealis-freight-airways@hackloop.mail,ORD SYD
Rheinufer Spedition,trucker,rheinufer-spedition@hackloop.mail,20 40
"""


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    (tmp_path / "kit").mkdir()
    (tmp_path / "kit" / "carrier-list.csv").write_text(CSV)
    s = settings.__class__(db_path=tmp_path / "app.db", kit_dir=tmp_path / "kit")
    for mod in (store, router, kit):
        monkeypatch.setattr(mod, "settings", s)
    kit.carriers.cache_clear()
    store._ready.clear()


def mail(i=1, sender="anna@customer.mail", subject="", body="", refs=(), attachments=()):
    return Mail.model_validate({
        "id": i, "from": sender, "to": settings.our_address, "subject": subject, "body": body,
        "in_reply_to": refs[-1] if refs else None, "references": list(refs),
        "received_at": "2026-11-21T16:00:00+00:00",
        "attachments": [{"id": n, "filename": f} for n, f in enumerate(attachments)],
    })


def kind(m):
    with store.connect() as db:
        return router.classify(m, db).kind


def quoted(thread_id, rfq_id="RFQ-1"):
    with store.connect() as db:
        db.execute(
            "INSERT INTO mail_outbox (thread_id, stage, rfq_id, recipient, state, created_at) VALUES (?,?,?,?,?,?)",
            (thread_id, "quote", rfq_id, "anna@customer.mail", "sent", time.time()),
        )


@pytest.mark.parametrize("subject,body", [
    ("Air freight quote MUC-JFK", "Hi, 3 pallets 120x80x100 cm, 450 kg total. Cheapest please."),
    ("Anfrage Luftfracht", "Hallo, bitte um ein Angebot FRA nach ORD, 2 Kolli, 300 kg."),
    ("Demande de devis", "Bonjour, fret aérien CDG à DXB, 5 colis, 120 kg."),
    ("Cotización", "Hola, necesito una cotización de carga aérea MAD a GRU, 4 bultos."),
    ("Preventivo", "Ciao, ci serve un preventivo trasporto aereo MXP-SIN, 10 colli."),
    ("Hello", "Could you help us with something going from Munich to Chicago next week?"),
])
def test_new_customer_threads_are_rfqs(subject, body):
    assert kind(mail(subject=subject, body=body)) == "rfq"


def test_desks():
    assert kind(mail(sender=settings.rate_desk, subject="Portal rates FRA-ORD")) == "portal_reply"
    assert kind(mail(sender=settings.tracking_desk, subject="Where is BK-12345678?")) == "tracking"
    assert kind(mail(sender=settings.our_address)) == "other"


def test_carrier_bid_vs_tariff():
    airline = "borealis-freight-airways@hackloop.mail"
    with store.connect() as db:
        db.execute(
            "INSERT INTO mail_outbox (thread_id, stage, recipient, state, created_at) VALUES (50, 'bid:borealis', ?, 'sent', ?)",
            (airline, time.time()),
        )
    assert kind(mail(51, airline, "Re: Bid request MUC-ORD", "We can offer 2.10 EUR/kg", refs=[50])) == "bid"
    assert kind(mail(60, airline, "Tariff December 2026", "Please find our new tariff attached.", attachments=["tariff.xlsx"])) == "tariff"
    assert kind(mail(61, "rheinufer-spedition@hackloop.mail", "Re: Pickup", "Pickup 85 EUR", refs=[55])) == "bid"


def test_booking_confirmation():
    m = mail(sender="borealis-freight-airways@hackloop.mail", subject="Booking BK-AB12CD34 confirmed")
    assert kind(m) == "booking_confirm"


@pytest.mark.parametrize("body", [
    "Yes, please book it.",
    "Ja, bitte buchen.",
    "Oui, d'accord, vous pouvez réserver.",
    "Sí, adelante.",
    "Va bene, procedete.",
    "Yes, no problem, book it",
    "Sounds good, go ahead",
])
def test_accept_in_quoted_thread(body):
    quoted(100)
    assert kind(mail(101, body=body, refs=[100])) == "accept"


@pytest.mark.parametrize("body", [
    "Could you check something cheaper?",
    "Yes, but is there a faster option?",
    "No thanks, too expensive.",
    "What is the transit time exactly?",
])
def test_not_accept_in_quoted_thread(body):
    quoted(100)
    assert kind(mail(101, body=body, refs=[100])) == "followup"


def test_quoted_reply_does_not_count_as_yes():
    body = "Can you also do 2 extra pallets?\n\nOn Sat, Lena wrote:\n> just reply yes and we'll book it"
    assert not is_acceptance(body)


def test_reply_before_quote_is_followup():
    with store.connect() as db:
        db.execute("INSERT INTO rfqs (id, thread_id, received_at, status) VALUES ('RFQ-9', '200', ?, 'SOURCING')", (time.time(),))
    with store.connect() as db:
        r = router.classify(mail(201, body="Sorry, it is 4 pallets not 3", refs=[200]), db)
    assert (r.kind, r.rfq_id) == ("followup", "RFQ-9")


def test_customer_tracking_question():
    assert kind(mail(subject="Where is my shipment?", body="Any update on the ETA?")) == "tracking"


def test_fresh_text_keeps_from_line_in_rfq():
    body = "From: MUC\nTo: JFK\n2 pallets 300 kg"
    assert "300 kg" in fresh_text(body)


def test_route_logs_event_and_saves_kind():
    from mail import poller

    m = mail(300, subject="Quote MUC-JFK", body="3 pallets")
    with store.connect() as db:
        poller.save(db, m)
    assert router.route(m).kind == "rfq"
    with store.connect() as db:
        assert db.execute("SELECT kind FROM mails WHERE id=300").fetchone()[0] == "rfq"
        ev = db.execute("SELECT agent, status, message FROM events").fetchone()
    assert ev[0] == "router" and ev[1] == "ok" and ev[2].startswith("rfq:")
