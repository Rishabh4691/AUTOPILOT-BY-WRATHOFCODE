from datetime import UTC, datetime

from core.agents.classifier import looks_like_rfq
from core.agents.trucker import parse_price
from core.contracts import Attachment, Mail
from mail.files import file_text, kind

TXT = b"Air freight quote request to PEK\nGross weight 1494 kg, volume 4.29 cbm, pickup 45299 Essen."
LETTER = (
    "Our price for this transport is 198.40 EUR (one hundred ninety-eight euros and forty cents).\n"
    "This price is all-in. It has a base charge of 49.00 EUR and a weight charge of 149.40 EUR."
)


def mail(body: str, subject: str, files: tuple[Attachment, ...]) -> Mail:
    return Mail(
        id=1, sender="a@b.c", to="us@x.y", subject=subject, body=body, in_reply_to=None,
        references=(), received_at=datetime.now(UTC), attachments=files,
    )


def test_txt_and_kind_by_bytes():
    assert "1494 kg" in file_text("quotation-request.txt", TXT, "text/plain")
    assert kind("noname", "", b"%PDF-1.7") == "pdf"
    assert kind("x.bin", "", b"\x89PNG....") == "image"


def test_request_only_in_attachment_is_an_rfq():
    files = (Attachment(id=9, filename="quotation-request.pdf", content_type="application/pdf"),)
    body = "please find our request for an air freight quotation attached, as a PDF file."
    assert looks_like_rfq(mail(body, "Request for quotation from Auer Maschinenbau GmbH", files))
    assert not looks_like_rfq(mail(body, "Request for quotation", ()))


def test_trucker_letter_total_not_base_charge():
    assert str(parse_price(LETTER)[0]) == "198.40"
