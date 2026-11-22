from __future__ import annotations

from pathlib import Path

import pytest

from mail.special import special_wishes
from tests.core.test_orchestrator import NOW, drain, harness, mail


@pytest.mark.parametrize(
    "text,want",
    [
        ("Please quote incl. truck pickup from our site in 1100 Vienna, Austria.", ["pickup outside Germany"]),
        ("Please include delivery to the consignee door in New York.", ["delivery at destination"]),
        ("Please include cargo insurance.", ["insurance"]),
        ("We deliver it to Frankfurt airport ourselves.", []),
        ("Pickup from our site in 65996 Wiesbaden, Germany.", []),
    ],
)
def test_special_wishes(text, want):
    assert special_wishes(text) == want


async def test_warns_but_still_quotes(tmp_path: Path):
    h = harness(tmp_path, now=NOW)
    h.orchestrator.route(mail(700, body="Please quote FRA to ORD, 100 kg, cheapest, and include cargo insurance."))
    await drain(h)
    assert len(h.mailbox.sent) == 1
    assert any(e.step == "special_request" and e.status.value == "warn" for e in h.sink.events)


async def test_priced_insurance_does_not_warn(tmp_path: Path):
    h = harness(tmp_path, now=NOW)
    body = (
        "Please quote FRA to ORD, 100 kg, cheapest. Please include cargo insurance in the all-in price: goods value "
        "22000 EUR, insured at 110 % of that value, premium rate 0.40 %."
    )
    h.orchestrator.route(mail(701, body=body))
    await drain(h)
    assert not any(e.step == "special_request" for e in h.sink.events)
