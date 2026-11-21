import json
from pathlib import Path

import httpx
import pytest
import respx

from core.agents.mailbox import (
    DryRunMailbox,
    HttpMailboxClient,
    MailShapeError,
    SendRejected,
    UnsafeRecipient,
    parse_mail,
)
from core.config import Settings, load_settings
from core.contracts import OutgoingMail

MAIL_DIR = Path(__file__).parent / "fixtures" / "mail"
BASE = "https://mail.test"
MESSAGES = f"{BASE}/v1/mailbox/messages"


def fixture_mail(name: str) -> dict[str, object]:
    loaded: dict[str, object] = json.loads((MAIL_DIR / name).read_text(encoding="utf-8"))
    return loaded


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(tmp_path, {"FIVEU_API_KEY": "test-key", "FIVEU_BASE_URL": BASE})


def test_parse_mail_maps_sender_and_ignores_unknown_fields() -> None:
    mail = parse_mail(fixture_mail("rfq_german_html.json"))
    assert mail.sender == "einkauf@kunde.de"
    assert mail.thread_root_id == 102
    english = parse_mail(fixture_mail("rfq_english.json"))
    assert english.sender == "buyer@example.com"


def test_parse_mail_reports_missing_fields() -> None:
    raw = fixture_mail("newsletter.json")
    del raw["from"]
    with pytest.raises(MailShapeError, match="from"):
        parse_mail(raw)


@respx.mock
async def test_poll_skips_malformed_items(settings: Settings) -> None:
    broken = {"id": 999, "subject": "no sender"}
    payload = {
        "messages": [fixture_mail("rfq_english.json"), broken, fixture_mail("carrier_bid.json")],
        "next_since_id": 205,
    }
    route = respx.get(MESSAGES).mock(return_value=httpx.Response(200, json=payload))
    async with httpx.AsyncClient() as client:
        mailbox = HttpMailboxClient(client, settings)
        mails, next_id = await mailbox.poll(100)
    assert [mail.id for mail in mails] == [101, 205]
    assert next_id == 205
    assert len(mailbox.last_shape_errors) == 1
    assert "999" in mailbox.last_shape_errors[0]
    sent = route.calls.last.request
    assert sent.url.params["since_id"] == "100"
    assert sent.headers["X-API-Key"] == "test-key"


@respx.mock
async def test_poll_without_next_since_id_uses_max_id(settings: Settings) -> None:
    payload = {"messages": [fixture_mail("carrier_bid.json")]}
    respx.get(MESSAGES).mock(return_value=httpx.Response(200, json=payload))
    async with httpx.AsyncClient() as client:
        _, next_id = await HttpMailboxClient(client, settings).poll(10)
    assert next_id == 205


@respx.mock
async def test_send_posts_json_with_in_reply_to(settings: Settings) -> None:
    stored = fixture_mail("newsletter.json") | {"id": 400, "in_reply_to": 101, "references": [101]}
    route = respx.post(MESSAGES).mock(return_value=httpx.Response(201, json=stored))
    outgoing = OutgoingMail(to="buyer@example.com", subject="Re: quote", body="Hi", in_reply_to=101)
    async with httpx.AsyncClient() as client:
        mail = await HttpMailboxClient(client, settings).send(outgoing)
    assert mail.id == 400
    assert json.loads(route.calls.last.request.content)["in_reply_to"] == 101


@respx.mock
async def test_send_rejected_on_client_error(settings: Settings) -> None:
    respx.post(MESSAGES).mock(return_value=httpx.Response(422, text="bad recipient"))
    outgoing = OutgoingMail(to="buyer@example.com", subject="Re", body="Hi", in_reply_to=101)
    async with httpx.AsyncClient() as client:
        with pytest.raises(SendRejected) as caught:
            await HttpMailboxClient(client, settings).send(outgoing)
    assert caught.value.status == 422


@respx.mock
async def test_send_refuses_our_own_address(settings: Settings) -> None:
    route = respx.post(MESSAGES).mock(return_value=httpx.Response(201, json={}))
    outgoing = OutgoingMail(to=settings.our_address, subject="Re", body="Hi", in_reply_to=1)
    async with httpx.AsyncClient() as client:
        with pytest.raises(UnsafeRecipient):
            await HttpMailboxClient(client, settings).send(outgoing)
    assert not route.called


@respx.mock
async def test_dry_run_never_sends(settings: Settings) -> None:
    route = respx.post(MESSAGES).mock(return_value=httpx.Response(201, json={}))
    outgoing = OutgoingMail(to="buyer@example.com", subject="Re", body="Hello", in_reply_to=101)
    async with httpx.AsyncClient() as client:
        mailbox = DryRunMailbox(HttpMailboxClient(client, settings), settings.our_address)
        mail = await mailbox.send(outgoing)
        with pytest.raises(UnsafeRecipient):
            await mailbox.send(outgoing.model_copy(update={"to": settings.our_address}))
    assert not route.called
    assert mail.id < 0
    assert mailbox.outbox == [outgoing]
