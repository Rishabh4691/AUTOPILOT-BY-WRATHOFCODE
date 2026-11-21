"""Bid replies state their expiry; the quote can then say 'for about N minutes'."""

from datetime import UTC, datetime

from core.agents.airline_bids import offer_valid_until

ULTRAVIOLET = (  # real reply, round 28
    "All-in price, including freight and all surcharges: 390.45 EUR\nTransit time: 4 days\n"
    "Offer valid until: 21 Nov 2026 18:00 UTC\n\nPlease quote reference R-M2SDYd0xvjzvCzMf when booking."
)
LUMEN = "Transit time: 1 day Offer valid until: 21 Nov 2026 18:00 UTC"


def test_offer_valid_until_is_read_from_real_bid_replies() -> None:
    assert offer_valid_until(ULTRAVIOLET) == datetime(2026, 11, 21, 18, 0, tzinfo=UTC)
    assert offer_valid_until(LUMEN) == datetime(2026, 11, 21, 18, 0, tzinfo=UTC)
    assert offer_valid_until("no expiry here") is None
