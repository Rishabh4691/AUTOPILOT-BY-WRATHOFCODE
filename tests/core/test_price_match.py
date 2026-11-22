"""Round 199: a customer asks us to match a competitor's lower rate; we keep the price and offer to book."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from tests.core.test_orchestrator import NOW, drain, harness, mail
from tests.core.test_revision import Box

MATCH = (
    "Thank you for your offer. It meets our requirements, and we would prefer to place the shipment with you.\n\n"
    "Another forwarder has offered a rate for the same shipment that is 10 percent lower. Would you be able to "
    "match their rate?\n\nKind regards\nAnna Sonnberg"
)


async def test_price_match_request_keeps_the_price_and_offers_to_book(tmp_path: Path):
    h = harness(tmp_path, now=NOW + timedelta(seconds=5))
    request = mail(24388)
    h.orchestrator.mailbox = Box(h.mailbox, request)
    h.orchestrator.route(request)
    await drain(h)
    assert len(h.mailbox.sent) == 1
    quoted = h.mailbox.sent[0]

    ask = mail(24642, subject="Re: Quote request FRA to ORD", body=MATCH, in_reply_to=10_001,
               references=(24388, 10_001))
    h.orchestrator.route(ask)
    await drain(h)
    assert len(h.mailbox.sent) == 2
    reply = h.mailbox.sent[1]
    assert reply.to == quoted.to and reply.in_reply_to == 24642
    assert "best all-in price" in reply.body and "can't go lower" in reply.body
    assert any(e.step == "price_match" for e in h.sink.events)

    thanks = mail(24650, subject="Re: Quote request FRA to ORD", body="Thank you for confirming the booking.",
                  in_reply_to=10_002, references=(24388, 10_002))
    h.orchestrator.route(thanks)
    await drain(h)
    assert len(h.mailbox.sent) == 2
