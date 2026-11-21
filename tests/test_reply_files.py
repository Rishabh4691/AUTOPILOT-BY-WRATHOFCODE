import base64
import json
from pathlib import Path

import httpx
import pytest
import respx

from core.agents.mailbox import HttpMailboxClient
from core.config import load_settings
from core.contracts import OutgoingMail
from mail import reply_files
from mail.files import file_text

BASE = "https://mail.test"
MESSAGES = f"{BASE}/v1/mailbox/messages"
ROUND76 = (
    "Please let me know the earliest possible arrival at DFW.\n\n"
    "Please attach your offer as a PDF to your reply, as our purchasing department needs it for filing.\n"
)
BODY = "Hi Deniz,\n\nthe fastest option is Fjordline Air Cargo for EUR 812.40 all-in, including the truck pickup.\n\nLena"


@pytest.mark.parametrize(
    "text,formats",
    [
        (ROUND76, ["pdf"]),
        ("Bitte senden Sie uns das Angebot als PDF und Excel.", ["pdf", "xlsx"]),
        ("Merci de joindre votre offre en format Word.", ["docx"]),
        ("请将报价以PDF附件发送。", ["pdf"]),
        ("見積書をPDFで添付してください。", ["pdf"]),
        ("Пожалуйста, пришлите предложение в формате PDF.", ["pdf"]),
        ("Please reply with a text file.", ["txt"]),
        ("Could you send a short video of the offer?", ["pdf"]),
        ("please find our request for an air freight quotation attached, as a PDF file (quotation-request.pdf).", []),
        ("Our packing list PDF is attached.", []),
        ("Please reply by mail with your all-in price in EUR.", []),
    ],
)
def test_wanted_formats(text, formats):
    assert reply_files.wanted(text) == formats


@pytest.mark.parametrize("fmt", ["pdf", "docx", "xlsx", "csv", "txt", "png", "jpg"])
def test_every_file_reads_back_with_the_price(fmt):
    data = reply_files.build(fmt, "Quotation WOC-21461", BODY, {"Total all-in": "812.40 EUR"})
    assert "812.40" in file_text(f"quotation.{fmt}", data)


def test_non_latin_pdf_still_carries_the_text():
    data = reply_files.build("pdf", "报价 WOC-1", "您好，我们的报价是 EUR 3,602.54 全包。")
    assert data[:5] == b"%PDF-"
    assert "3,602.54" in file_text("q.pdf", data) or "3602" in file_text("q.pdf", data)


def test_quote_attachments_only_when_asked():
    reply_files.remember(76, "Request\n" + ROUND76)
    files = reply_files.quote_attachments(76, "Re: quote", BODY, "WOC-76")
    assert [f["filename"] for f in files] == ["quotation-WOC-76.pdf"]
    assert base64.b64decode(files[0]["content_base64"])[:5] == b"%PDF-"
    reply_files.remember(77, "Please quote 3 pieces, 400 kg.")
    assert reply_files.quote_attachments(77, "Re: quote", BODY) == []


@respx.mock
async def test_send_posts_attachments_and_omits_empty_list(tmp_path: Path):
    settings = load_settings(tmp_path, {"FIVEU_API_KEY": "k", "FIVEU_BASE_URL": BASE})
    stored = {"id": 9, "from": settings.our_address or "us@x", "to": "c@x", "subject": "Re", "body": "Hi",
              "received_at": "2026-11-21T22:38:00+00:00", "in_reply_to": 1, "references": [1]}
    route = respx.post(MESSAGES).mock(return_value=httpx.Response(201, json=stored))
    pdf = {"filename": "q.pdf", "content_type": "application/pdf", "content_base64": "JVBERi0="}
    async with httpx.AsyncClient() as client:
        box = HttpMailboxClient(client, settings)
        await box.send(OutgoingMail(to="c@x", subject="Re", body="Hi", in_reply_to=1, attachments=(pdf,)))
        assert json.loads(route.calls.last.request.content)["attachments"] == [pdf]
        await box.send(OutgoingMail(to="c@x", subject="Re", body="Hi", in_reply_to=1))
        assert "attachments" not in json.loads(route.calls.last.request.content)
