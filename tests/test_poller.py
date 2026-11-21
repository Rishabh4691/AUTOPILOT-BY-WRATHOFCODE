import asyncio

import pytest

from mail import poller as pl
from mail import store
from mail.client import Mail
from mail.config import settings


def mail(i, refs=(), sender="anna@customer.mail", subject="Quote MUC-JFK"):
    return {
        "id": i,
        "from": sender,
        "to": settings.our_address,
        "subject": subject,
        "body": "hello",
        "in_reply_to": refs[-1] if refs else None,
        "references": list(refs),
        "received_at": "2026-11-21T16:00:00+00:00",
        "attachments": [],
    }


class FakeClient:
    def __init__(self, inbox):
        self.inbox = [Mail.model_validate(m) for m in inbox]
        self.calls = []

    async def list_messages(self, since_id=0, limit=200):
        self.calls.append(since_id)
        out = [m for m in self.inbox if m.id > since_id][:limit]
        return out, max([since_id] + [m.id for m in out])


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    monkeypatch.setattr(store, "settings", settings.__class__(db_path=path))
    monkeypatch.setattr(pl, "settings", settings.__class__(db_path=path))
    store._ready.clear()
    return path


async def settle(p):
    while p.running:
        await asyncio.gather(*p.running.values(), return_exceptions=True)


def states():
    with store.connect() as db:
        return {r[0]: (r[1], r[2]) for r in db.execute("SELECT id, state, attempts FROM mails")}


async def test_stores_and_handles_each_mail_once():
    seen = []

    async def handler(m):
        seen.append(m.id)

    client = FakeClient([mail(1), mail(2)])
    p = pl.Poller(client, handler)
    assert await p.poll_once() == [1, 2]
    await settle(p)
    assert await p.poll_once() == []
    await settle(p)
    assert seen == [1, 2]
    assert client.calls == [0, 2]
    assert states() == {1: ("done", 1), 2: ("done", 1)}


async def test_since_id_survives_restart():
    client = FakeClient([mail(5)])
    p = pl.Poller(client)
    await p.poll_once()
    await settle(p)
    client2 = FakeClient([mail(5), mail(6)])
    assert await pl.Poller(client2).poll_once() == [6]
    assert client2.calls == [5]


async def test_same_mail_twice_from_api_is_ignored():
    seen = []

    async def handler(m):
        seen.append(m.id)

    class Replaying(FakeClient):
        async def list_messages(self, since_id=0, limit=200):
            return self.inbox, 0

    p = pl.Poller(Replaying([mail(7)]), handler)
    await p.poll_once()
    await settle(p)
    await p.poll_once()
    await settle(p)
    assert seen == [7]


async def test_failed_handler_retries_then_gives_up():
    calls = []

    async def boom(m):
        calls.append(m.id)
        raise ValueError("bad mail")

    p = pl.Poller(FakeClient([mail(9)]), boom)
    await p.poll_once()
    await settle(p)
    for _ in range(5):
        for mid in p.pending():
            p.dispatch(mid)
        await settle(p)
    assert calls == [9, 9, 9]
    assert states()[9] == ("error", 3)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE status='fail'").fetchone()[0] == 3


async def test_crash_mid_handler_is_resumed_on_start():
    with store.connect() as db:
        pl.save(db, Mail.model_validate(mail(11)))
        db.execute("UPDATE mails SET state='working', attempts=1 WHERE id=11")
    seen = []

    async def handler(m):
        seen.append(m.id)

    p = pl.Poller(FakeClient([]), handler)
    assert p.pending() == [11]
    p.dispatch(11)
    await settle(p)
    assert seen == [11] and states()[11] == ("done", 2)


async def test_mails_in_one_thread_run_in_order():
    order = []

    async def handler(m):
        order.append(("start", m.id))
        await asyncio.sleep(0.05 if m.id == 20 else 0)
        order.append(("end", m.id))

    p = pl.Poller(FakeClient([mail(20), mail(21, refs=[20])]), handler)
    await p.poll_once()
    await settle(p)
    assert order == [("start", 20), ("end", 20), ("start", 21), ("end", 21)]


async def test_own_mails_are_skipped():
    p = pl.Poller(FakeClient([mail(30, sender=settings.our_address)]))
    assert await p.poll_once() == []


def test_thread_id_saved_from_references():
    with store.connect() as db:
        pl.save(db, Mail.model_validate(mail(41, refs=[40])))
        assert db.execute("SELECT thread_id FROM mails WHERE id=41").fetchone()[0] == 40


def test_second_bot_is_refused(tmp_path):
    lock = pl.single_instance(tmp_path / "bot.lock")
    with pytest.raises(pl.AlreadyRunning):
        pl.single_instance(tmp_path / "bot.lock")
    lock.close()
    pl.single_instance(tmp_path / "bot.lock").close()
