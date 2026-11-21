import pytest

from mail.lock import AlreadyRunning, single_instance
from mail.text import fresh_text, reply_subject


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
