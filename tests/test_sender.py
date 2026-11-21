import asyncio
import time

import pytest

from mail import kit, router, sender as sd, store
from mail.client import Mail, MailboxError
from mail.config import settings

CSV = "name,kind,email,serves\nBorealis Freight Airways,airline,borealis-freight-airways@hackloop.mail,ORD\n"


class FakeClient:
    def __init__(self, fail=None, dry=False):
        self.sent = []
        self.fail = fail
        self.dry = dry

    async def send_message(self, to, subject, body, in_reply_to=None, attachments=None):
        await asyncio.sleep(0)
        if self.fail:
            raise self.fail
        self.sent.append({"to": to, "subject": subject, "body": body, "in_reply_to": in_reply_to})
        if self.dry:
            return {"id": -len(self.sent), "dry_run": True}
        return {"id": 1000 + len(self.sent), "received_at": "2026-11-21T16:01:00+00:00"}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    (tmp_path / "kit").mkdir()
    (tmp_path / "kit" / "carrier-list.csv").write_text(CSV)
    s = settings.__class__(db_path=tmp_path / "app.db", kit_dir=tmp_path / "kit", dry_run=False)
    for mod in (store, sd, kit, router):
        monkeypatch.setattr(mod, "settings", s)
    kit.carriers.cache_clear()
    store._ready.clear()


def rfq_mail(i=500, refs=()):
    return Mail.model_validate({"id": i, "from": "anna@customer.mail", "subject": "Quote MUC-JFK", "body": "3 pallets",
                                "references": list(refs), "in_reply_to": refs[-1] if refs else None})


async def test_quote_goes_out_once_in_the_customers_thread():
    c = FakeClient()
    s = sd.Sender(c)
    m = rfq_mail()
    first = await s.reply(m, "quote", "Re: Quote MUC-JFK", "Hi Anna", rfq_id="RFQ-1")
    second = await s.reply(m, "quote", "Re: Quote MUC-JFK", "Hi Anna again", rfq_id="RFQ-1")
    assert first.ok and first.message_id == 1001
    assert not second.ok and "already sent" in second.reason
    assert c.sent == [{"to": "anna@customer.mail", "subject": "Re: Quote MUC-JFK", "body": "Hi Anna", "in_reply_to": 500}]
    with store.connect() as db:
        out = db.execute("SELECT direction, thread_id, kind FROM mails WHERE id=1001").fetchone()
    assert tuple(out) == ("out", 500, "quote")


async def test_two_quotes_racing_send_only_one():
    c = FakeClient()
    s = sd.Sender(c)
    m = rfq_mail()
    results = await asyncio.gather(*[s.reply(m, "quote", "Re", f"body {i}") for i in range(5)])
    assert sum(r.ok for r in results) == 1 and len(c.sent) == 1


async def test_second_sender_object_also_blocked():
    m = rfq_mail()
    await sd.Sender(FakeClient()).reply(m, "quote", "Re", "one")
    c2 = FakeClient()
    assert not (await sd.Sender(c2).reply(m, "quote", "Re", "two")).ok
    assert c2.sent == []


async def test_no_acknowledgement_before_quote():
    c = FakeClient()
    r = await sd.Sender(c).reply(rfq_mail(), "followup", "Re", "We received your request")
    assert not r.ok and "must be the quote" in r.reason and c.sent == []


async def test_booking_confirmation_after_quote_is_allowed():
    c = FakeClient()
    s = sd.Sender(c)
    await s.reply(rfq_mail(), "quote", "Re", "quote")
    r = await s.reply(rfq_mail(501, refs=[500]), "booking", "Re", "Booked")
    assert r.ok and c.sent[-1]["in_reply_to"] == 501


async def test_carriers_can_be_mailed_any_time():
    c = FakeClient()
    r = await sd.Sender(c).send(thread_id=900, stage="bid:borealis", to="borealis-freight-airways@hackloop.mail",
                                subject="Bid request", body="...", in_reply_to=None)
    assert r.ok


async def test_human_takeover_blocks_send():
    with store.connect() as db:
        db.execute("INSERT INTO rfqs (id, thread_id, received_at, status, human_takeover) VALUES ('RFQ-1', '500', ?, 'PRICED', 1)", (time.time(),))
    c = FakeClient()
    r = await sd.Sender(c).reply(rfq_mail(), "quote", "Re", "quote", rfq_id="RFQ-1")
    assert not r.ok and "human" in r.reason and c.sent == []


async def test_definite_failure_frees_the_slot():
    m = rfq_mail()
    r = await sd.Sender(FakeClient(fail=MailboxError(422, "bad address"))).reply(m, "quote", "Re", "x")
    assert not r.ok
    assert (await sd.Sender(FakeClient()).reply(m, "quote", "Re", "x")).ok


async def test_maybe_sent_failure_is_never_retried():
    m = rfq_mail()
    await sd.Sender(FakeClient(fail=MailboxError(0, "ReadTimeout", maybe_sent=True))).reply(m, "quote", "Re", "x")
    c = FakeClient()
    assert not (await sd.Sender(c).reply(m, "quote", "Re", "x")).ok and c.sent == []
    with store.connect() as db:
        assert db.execute("SELECT state FROM outbox").fetchone()[0] == "unknown"


async def test_dry_run_rows_are_cleared_when_going_live(monkeypatch):
    m = rfq_mail()
    monkeypatch.setattr(sd, "settings", sd.settings.__class__(db_path=sd.settings.db_path, kit_dir=sd.settings.kit_dir, dry_run=True))
    assert (await sd.Sender(FakeClient(dry=True)).reply(m, "quote", "Re", "x")).reason == "dry_run"
    monkeypatch.setattr(sd, "settings", sd.settings.__class__(db_path=sd.settings.db_path, kit_dir=sd.settings.kit_dir, dry_run=False))
    c = FakeClient()
    assert (await sd.Sender(c).reply(m, "quote", "Re", "x")).ok and len(c.sent) == 1


async def test_router_sees_quote_after_send():
    await sd.Sender(FakeClient()).reply(rfq_mail(), "quote", "Re", "x", rfq_id="RFQ-1")
    yes = Mail.model_validate({"id": 502, "from": "anna@customer.mail", "body": "Yes, book it", "references": [500], "in_reply_to": 1001})
    with store.connect() as db:
        r = router.classify(yes, db)
    assert (r.kind, r.rfq_id) == ("accept", "RFQ-1")
