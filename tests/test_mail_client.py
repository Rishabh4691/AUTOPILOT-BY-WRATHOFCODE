import httpx
import pytest

from mail import client as mc
from mail.client import Mail, MailboxError, MailClient, reply_subject

RATEDESK = {
    "id": 136,
    "from": "ratedesk@hackloop.mail",
    "to": "wrathofcode@hackloop.mail",
    "subject": "Portal rates FRA-ORD 100.0 kg",
    "body": "Hello,\n\nportal rates for FRA-ORD ...",
    "in_reply_to": None,
    "references": [],
    "received_at": "2026-11-21T14:08:21.818425+00:00",
    "attachments": [],
}


def make(handler):
    return MailClient(httpx.AsyncClient(base_url="https://x", transport=httpx.MockTransport(handler)))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr(mc.asyncio, "sleep", instant)


def live(monkeypatch):
    monkeypatch.setattr(mc, "settings", mc.settings.__class__(dry_run=False, kill_switch=False))


def test_mail_model_and_thread():
    m = Mail.model_validate(RATEDESK)
    assert m.sender_email == "ratedesk@hackloop.mail"
    assert m.thread_id == 136
    reply = Mail.model_validate({**RATEDESK, "id": 140, "in_reply_to": 138, "references": [120, 138]})
    assert reply.thread_id == 120
    named = Mail.model_validate({**RATEDESK, "from": "Anna Kowalska <Anna@Customer.mail>"})
    assert named.sender_email == "anna@customer.mail"


async def test_list_messages():
    def handler(req):
        assert req.url.params["since_id"] == "100"
        return httpx.Response(200, json={"messages": [RATEDESK], "next_since_id": 136})

    mails, nxt = await make(handler).list_messages(100)
    assert [m.id for m in mails] == [136] and nxt == 136


async def test_list_retries_on_429():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"messages": [], "next_since_id": 5})

    assert (await make(handler).list_messages(5))[1] == 5
    assert len(calls) == 2


async def test_send_puts_in_reply_to(monkeypatch):
    live(monkeypatch)
    seen = {}

    def handler(req):
        import json

        seen.update(json.loads(req.content))
        return httpx.Response(201, json={"id": 200, **seen})

    out = await make(handler).send_message("anna@x.mail", "Re: Quote", "Hi", in_reply_to=136)
    assert seen == {"to": "anna@x.mail", "subject": "Re: Quote", "body": "Hi", "in_reply_to": 136}
    assert out["id"] == 200


async def test_send_never_retries_server_error(monkeypatch):
    live(monkeypatch)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(502)

    with pytest.raises(MailboxError):
        await make(handler).send_message("a@x.mail", "s", "b", in_reply_to=1)
    assert len(calls) == 1


async def test_dry_run_does_not_call_api(capsys):
    def handler(req):
        raise AssertionError("should not send")

    out = await make(handler).send_message("a@x.mail", "s", "hello", in_reply_to=1)
    assert out["dry_run"] and out["id"] < 0
    assert "[DRY_RUN]" in capsys.readouterr().out


def test_reply_subject():
    assert reply_subject("Quote MUC-JFK") == "Re: Quote MUC-JFK"
    assert reply_subject("RE: Quote") == "RE: Quote"
    assert reply_subject("AW: Anfrage") == "AW: Anfrage"
