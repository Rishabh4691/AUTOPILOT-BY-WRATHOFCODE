from datetime import UTC, datetime
from decimal import Decimal

from core.contracts import RFQ, PriceOption, Preference
from core.orchestrator import convert_money, in_currency, quote_currency
from sourcing import fx


def rfq(currency: str | None) -> RFQ:
    return RFQ(
        mail_id=1,
        thread_root_id=1,
        customer="c@x",
        subject="s",
        origin="FRA",
        destination="ORD",
        pieces=(),
        gross_kg=Decimal("100"),
        door_pickup=False,
        preference=Preference.CHEAPEST,
        preference_assumed=False,
        currency=currency,
        received_at=datetime(2026, 11, 21, tzinfo=UTC),
    )


def option(total: str, currency: str) -> PriceOption:
    return PriceOption(
        source="sheet",
        carrier=f"{currency} Air",
        total=Decimal(total),
        currency=currency,
        transit_days=3,
    )


def test_usd_option_is_converted_and_compared_in_eur() -> None:
    fx.set_rate("USD", "0.90")
    options = in_currency([option("1000", "EUR"), option("1000", "USD")], "EUR")
    totals = sorted(o.total for o in options)
    assert totals == [Decimal("900.00"), Decimal("1000.00")]
    assert {o.currency for o in options} == {"EUR"}


def test_customer_currency_wins_and_eur_is_default() -> None:
    options = [option("10", "EUR")]
    assert quote_currency(rfq("USD"), options) == "USD"
    assert quote_currency(rfq(None), options) == "EUR"


def test_unknown_rate_keeps_original_currency() -> None:
    assert convert_money(Decimal("5"), "XYZ", "EUR") is None
    assert [o.currency for o in in_currency([option("5", "XYZ")], "EUR")] == ["XYZ"]
