import pytest

from mail.lock import AlreadyRunning, single_instance
from mail.text import fresh_text, reply_subject, request_text

FORWARD = (
    "Hi team,\n\nplease quote the request below for our customer.\n\nThanks,\nMarc\n\n"
    "---------- Forwarded message ---------\nFrom: Tobias <buyer@client.mail>\n"
    "Sent: Friday, November 20, 2026 09:12\nSubject: Air freight quote to KUL\n\n"
    "Please quote STR to KUL. 6 pieces, 660 kg, 2.1 cbm.\nContents: lithium-ion batteries.\n"
    "Regards\nTobias\n\n-----Original Message-----\nFrom: Sales <sales@forwarder.mail>\n"
    "Sent: Monday\n\nLast time: 999 kg, Currency USD."
)


def test_forward_uses_the_forwarded_request_when_the_new_text_has_no_cargo():
    text = request_text("FW: Air freight quote to KUL", FORWARD)
    assert "660 kg" in text and "lithium" in text and "999 kg" not in text
    assert request_text("RE: Air freight quote to KUL", FORWARD) == fresh_text(FORWARD)
    assert "Marc" in request_text("FW: x", "Please quote FRA to JFK, 300 kg.\nMarc\n\nFrom: a@b.c\nold 9 kg")


def test_forward_with_dangerous_goods_in_the_quoted_part_is_dangerous():
    from mail.dg import check

    assert check(request_text("Fwd: RFQ", FORWARD), []).dangerous


def test_fresh_text_drops_quoted_history():
    body = "Please add 2 pallets.\n\nOn Fri, Lena wrote:\n> just reply yes and we'll book it"
    assert fresh_text(body) == "Please add 2 pallets."


def test_fresh_text_keeps_from_line_in_rfq():
    assert "300 kg" in fresh_text("From: MUC\nTo: JFK\n2 pallets 300 kg")


def test_reply_subject():
    assert reply_subject("Quote MUC-JFK") == "Re: Quote MUC-JFK"
    assert reply_subject("AW: Anfrage") == "AW: Anfrage"


def test_only_one_bot(tmp_path):
    lock = single_instance(tmp_path / "bot.lock")
    with pytest.raises(AlreadyRunning):
        single_instance(tmp_path / "bot.lock")
    lock.close()
    single_instance(tmp_path / "bot.lock").close()
