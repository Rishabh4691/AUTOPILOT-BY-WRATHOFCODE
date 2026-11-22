from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from mail.extract import revised_figures
from tests.core.test_orchestrator import NOW, drain, harness, mail

ROUND86 = (
    "Hi there,\n\nHope your day's going well! Sorry for the change, the final packing list came in, and the shipment "
    "details have changed to:\n\n5 pieces, 1317 kg gross weight, 8.18 cbm\n\nEverything else stays the same. Could you "
    "please update your offer?\n\nThanks for your help!\n\nCheers,\nKlaus Weidner"
)
ROUND87 = (
    "Hi there,\n\nHope your day's going well! Sorry for the change, the final packing list has come in, and the shipment "
    "details have changed to:\n\n13 pieces, 611 kg gross weight, 5.71 cbm\n\nEverything else stays the same. Could you "
    "update your offer with these figures, please?\n\nThanks a lot and have a lovely day!\nPetra Hofmann"
)


@pytest.mark.parametrize(
    "text,want",
    [
        (ROUND86, {"gross_kg": Decimal("1317"), "volume_cbm": Decimal("8.18"), "pieces": 5}),
        (ROUND87, {"gross_kg": Decimal("611"), "volume_cbm": Decimal("5.71"), "pieces": 13}),
        ("Die Daten haben sich geändert: jetzt 4 Paletten, 980 kg brutto, 3,2 cbm. Bitte Angebot aktualisieren.",
         {"gross_kg": Decimal("980"), "volume_cbm": Decimal("3.2"), "pieces": 4}),
        ("数据有变更：现在 6 件，毛重 820 kg，体积 3.9 cbm。请更新报价。",
         {"gross_kg": Decimal("820"), "volume_cbm": Decimal("3.9"), "pieces": 6}),
        ("Sorry, correction: 2 pallets 120 x 80 x 100 cm, 450 kg total.",
         {"gross_kg": Decimal("450"), "volume_cbm": Decimal("1.92"), "pieces": 2}),
    ],
)
def test_revised_figures(text, want):
    got = revised_figures(text)
    assert {k: (Decimal(str(v)) if k != "pieces" else v) for k, v in got.items()} == want


@pytest.mark.parametrize(
    "text",
    [
        "Thank you for your offer. That works for us, please go ahead and book it.",
        "Thank you for confirming the booking. Please let me know if anything changes.",
        "Could you also check a faster option?",
    ],
)
def test_no_revision(text):
    assert revised_figures(text) == {}


class Box:
    def __init__(self, inner, original):
        self.inner, self.original = inner, original

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def read_one(self, message_id):
        assert message_id == self.original.id
        return self.original


async def test_change_mail_gets_one_updated_quote(tmp_path: Path):
    h = harness(tmp_path, now=NOW + timedelta(seconds=5))
    request = mail(24388)
    h.orchestrator.mailbox = Box(h.mailbox, request)
    h.orchestrator.route(request)
    await drain(h)
    assert len(h.mailbox.sent) == 1
    first = h.mailbox.sent[0]

    change = mail(24642, subject="Re: Quote request FRA to ORD", body=ROUND86, in_reply_to=10_001, references=(24388, 10_001))
    h.orchestrator.route(change)
    await drain(h)
    assert len(h.mailbox.sent) == 2
    updated = h.mailbox.sent[1]
    assert updated.in_reply_to == 24642 and updated.to == first.to
    revised = [e for e in h.sink.events if e.step == "revised"]
    assert revised and "1317" in revised[0].message and "8.18" in revised[0].message

    again = mail(24700, subject="Re: Quote request FRA to ORD", body=ROUND86, in_reply_to=10_002, references=(24388, 10_002))
    yes = mail(24701, subject="Re: Quote request FRA to ORD", body="That works for us, please book it.", in_reply_to=10_002, references=(24388, 10_002))
    h.orchestrator.route(again)
    h.orchestrator.route(yes)
    await drain(h)
    assert len(h.mailbox.sent) == 2


async def test_change_mail_without_our_quote_is_ignored(tmp_path: Path):
    h = harness(tmp_path)
    change = mail(30000, subject="Re: something", body=ROUND87, in_reply_to=29999, references=(29990, 29999))
    h.orchestrator.route(change)
    await drain(h)
    assert h.mailbox.sent == []


async def test_second_and_third_change_are_quoted_and_keep_earlier_changes(tmp_path: Path):
    # User, 09:23 (after round 172): every further change must be quoted again, not just the first.
    h = harness(tmp_path, now=NOW + timedelta(seconds=5))
    request = mail(24388)
    h.orchestrator.mailbox = Box(h.mailbox, request)
    h.orchestrator.route(request)
    await drain(h)
    first = mail(24642, subject="Re: Quote request FRA to ORD", body=ROUND86, in_reply_to=10_001, references=(24388, 10_001))
    h.orchestrator.route(first)
    await drain(h)
    assert len(h.mailbox.sent) == 2
    second = mail(24650, subject="Re: Quote request FRA to ORD",
                  body="Sorry, one more change: the gross weight is now 1400 kg. Please update your offer.",
                  in_reply_to=10_002, references=(24388, 10_002))
    h.orchestrator.route(second)
    await drain(h)
    assert len(h.mailbox.sent) == 3 and h.mailbox.sent[2].in_reply_to == 24650
    revised = [e.message for e in h.sink.events if e.step == "revised"]
    assert "1400" in revised[-1] and "8.18" in revised[-1]  # the earlier new volume is kept
    third = mail(24660, subject="Re: Quote request FRA to ORD",
                 body="Final change, promise: 6 pieces, 1450 kg gross weight, 8.5 cbm. Please update the offer.",
                 in_reply_to=10_003, references=(24388, 10_003))
    h.orchestrator.route(third)
    await drain(h)
    assert len(h.mailbox.sent) == 4
    assert "1450" in [e.message for e in h.sink.events if e.step == "revised"][-1]
