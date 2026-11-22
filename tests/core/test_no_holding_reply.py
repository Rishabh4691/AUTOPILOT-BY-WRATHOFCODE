"""Round 121 (declined_in_scope): a reviewed body promised to 'come back to you' with no price."""

import pytest

from core.orchestrator import holding_reply

ROUND_121 = (
    "Dear Ms Sonnberg,\n\nThank you for your request for the fastest air freight option from Frankfurt to "
    "Beijing for your 9 pieces of textile samples, 700 kg and 6.58 cbm, ready on Fri 27 Nov.\n\nThe airline "
    "serving this route currently cannot confirm a rate, as its rate system is temporarily unavailable. Rather "
    "than send you an estimate that might change, I will come back to you with a confirmed all-in price in EUR, "
    "the earliest departure and the expected arrival at PEK as soon as the rate is available again.\n\n"
    "Our reference is WOC-36109.\n\nKind regards,\nLena Hartmann"
)


@pytest.mark.parametrize("body", [
    ROUND_121,
    "Thanks, we are checking rates and will get back to you shortly.",
    "Vielen Dank, wir melden uns bei Ihnen zurück, sobald der Preis feststeht.",
    "Hi Anna,\n\nthanks for the request, we will send you the price once the airline confirms.",
])
def test_holding_replies_are_caught(body: str) -> None:
    assert holding_reply(body)


@pytest.mark.parametrize("body", [
    "Hi Anna,\n\nYour all-in price is EUR 3,160.07, covering air freight, fuel, security and door pickup. "
    "Reply yes and I'll book it.",
    "Der All-in-Preis beträgt 4.455,22 EUR inklusive Abholung.",
    "The total is € 1,037.07, all in.",
])
def test_priced_quotes_pass(body: str) -> None:
    assert not holding_reply(body)
