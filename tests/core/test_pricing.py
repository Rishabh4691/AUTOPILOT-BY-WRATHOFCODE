from decimal import Decimal

import pytest

from core.contracts import Piece, Preference, PriceOption
from core.pricing.assemble import all_in_total, build_breakdown
from core.pricing.money import CurrencyError, add_all, convert
from core.pricing.selection import balanced_score, select, select_balanced
from core.pricing.tariff import LaneTariff, TariffError, price_lane
from core.pricing.units import UnitsError, inch_to_cm, lb_to_kg, parse_decimal
from core.pricing.weight import chargeable_kg, round_up_half_kg, volume_cbm, volume_kg

D = Decimal

FRA_ORD = LaneTariff(
    airline="Yellowtail",
    origin="FRA",
    destination="ORD",
    currency="EUR",
    transit_days=4,
    minimum=D("110"),
    breaks=(
        (D("0"), D("3.73")),
        (D("45"), D("3.32")),
        (D("100"), D("2.42")),
        (D("250"), D("1.82")),
        (D("500"), D("1.64")),
        (D("1000"), D("1.46")),
        (D("2000"), D("1.14")),
    ),
    surcharges_per_kg=(("fuel", D("0.66")), ("security", D("0.11"))),
)


def option(carrier: str, total: str, transit: int, currency: str = "EUR") -> PriceOption:
    return PriceOption(
        source="test", carrier=carrier, total=D(total), currency=currency, transit_days=transit
    )


def test_minimum_applies_to_freight_only() -> None:
    price = price_lane(FRA_ORD, D("10"))
    assert price.freight == D("110.00")
    assert price.total == D("117.70")


def test_next_break_wins_at_95_kg() -> None:
    price = price_lane(FRA_ORD, D("95"))
    assert price.billed_kg == D("100")
    assert price.rate == D("2.42")
    assert price.total == D("319.00")


def test_actual_weight_kept_at_300_kg() -> None:
    price = price_lane(FRA_ORD, D("300"))
    assert price.billed_kg == D("300")
    assert price.freight == D("546.00")
    assert price.surcharges == (("fuel", D("198.00")), ("security", D("33.00")))
    assert price.total == D("777.00")


def test_above_last_break_uses_last_rate() -> None:
    price = price_lane(FRA_ORD, D("2500"))
    assert price.rate == D("1.14")


def test_flat_fees_added() -> None:
    tariff = LaneTariff(
        airline="X",
        origin="FRA",
        destination="ORD",
        currency="EUR",
        transit_days=2,
        minimum=D("0"),
        breaks=((D("0"), D("1")),),
        flat_fees=(("awb", D("25")),),
    )
    assert price_lane(tariff, D("10")).total == D("35.00")


@pytest.mark.parametrize(
    "breaks",
    [
        (),
        ((D("45"), D("1")),),
        ((D("0"), D("2")), (D("0"), D("1"))),
        ((D("0"), D("0")),),
    ],
)
def test_invalid_breaks_rejected(breaks: tuple[tuple[Decimal, Decimal], ...]) -> None:
    tariff = LaneTariff("X", "FRA", "ORD", "EUR", 1, D("10"), breaks)
    with pytest.raises(TariffError):
        price_lane(tariff, D("10"))


def test_volume_from_pieces() -> None:
    pieces = (Piece(count=2, length_cm=D("120"), width_cm=D("80"), height_cm=D("100")),)
    assert volume_cbm(pieces) == D("1.92")
    assert volume_kg(D("1.92")) == D("320.64")
    assert chargeable_kg(D("200"), pieces) == D("321.0")


def test_volume_from_explicit_cbm() -> None:
    assert volume_kg(D("0.5")) == D("83.5")
    assert chargeable_kg(D("50"), cbm=D("0.5")) == D("83.5")
    assert chargeable_kg(D("90"), cbm=D("0.5")) == D("90.0")


def test_volume_factor_is_a_parameter() -> None:
    assert chargeable_kg(D("1"), cbm=D("1"), factor=D("200")) == D("200.0")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("10.01", "10.5"), ("10.5", "10.5"), ("10.0", "10.0"), ("10.51", "11.0")],
)
def test_round_up_half_kg(value: str, expected: str) -> None:
    assert round_up_half_kg(D(value)) == D(expected)


def test_imperial_conversions() -> None:
    assert lb_to_kg(D("100")) == D("45.359237")
    assert inch_to_cm(D("10")) == D("25.4")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12,5", "12.5"),
        ("1.250,50", "1250.50"),
        ("1,250.50", "1250.50"),
        ("1250", "1250"),
        (" 1 250 ", "1250"),
        ("1" + chr(0xA0) + "250,5", "1250.5"),
        ("1,250", "1250"),
        ("0,250", "0.250"),
    ],
)
def test_parse_decimal(text: str, expected: str) -> None:
    assert parse_decimal(text) == D(expected)


def test_parse_decimal_rejects_garbage() -> None:
    with pytest.raises(UnitsError):
        parse_decimal("abc")


def test_convert_with_fx() -> None:
    fx = {"USD": D("0.92")}
    assert convert(D("100"), "USD", "EUR", fx) == D("92.00")
    assert convert(D("92"), "EUR", "USD", fx) == D("100.00")
    assert convert(D("10.005"), "EUR", "EUR", {}) == D("10.01")


def test_missing_fx_raises() -> None:
    with pytest.raises(CurrencyError):
        convert(D("1"), "GBP", "EUR", {})


def test_add_all_converts_before_summing() -> None:
    assert add_all([(D("100"), "EUR"), (D("100"), "USD")], "EUR", {"USD": D("0.9")}) == D("190.00")


def test_all_in_total() -> None:
    fx = {"USD": D("0.9")}
    assert all_in_total(D("319"), "EUR", None, None, "EUR", fx) == D("319.00")
    assert all_in_total(D("319"), "EUR", D("100"), "USD", "EUR", fx) == D("409.00")
    with pytest.raises(CurrencyError):
        all_in_total(D("319"), "EUR", D("100"), None, "EUR", fx)


def test_build_breakdown() -> None:
    lane = price_lane(FRA_ORD, D("95"))
    breakdown = build_breakdown(lane, D("95"), pickup=D("50"))
    assert breakdown.freight == D("242.00")
    assert breakdown.fuel == D("66.00")
    assert breakdown.security == D("11.00")
    assert breakdown.other_surcharges == D("0")
    assert breakdown.pickup == D("50.00")


def test_select_cheapest_and_fastest() -> None:
    options = [option("A", "500", 5), option("B", "600", 2), option("C", "700", 2)]
    assert select(options, Preference.CHEAPEST).carrier == "A"
    assert select(options, Preference.FASTEST).carrier == "B"


def test_select_tie_breaks() -> None:
    cheap_tie = [option("Z", "500", 3), option("Y", "500", 2), option("X", "500", 2)]
    assert select(cheap_tie, Preference.CHEAPEST).carrier == "X"
    fast_tie = [option("A", "600", 2), option("B", "550", 2)]
    assert select(fast_tie, Preference.FASTEST).carrier == "B"


def test_select_rejects_mixed_currency() -> None:
    with pytest.raises(CurrencyError):
        select([option("A", "1", 1), option("B", "1", 1, "USD")], Preference.CHEAPEST)


def test_balanced_score_three_bids() -> None:
    bids = [option("A", "1000", 5), option("B", "1200", 3), option("C", "1500", 2)]
    assert balanced_score(bids[0], D("1000"), 2) == D("1.75")
    assert balanced_score(bids[1], D("1000"), 2) == D("1.35")
    assert balanced_score(bids[2], D("1000"), 2) == D("1.25")
    assert select_balanced(bids).carrier == "C"
    assert select_balanced(bids, D("0.9"), D("0.1")).carrier == "A"


def test_balanced_score_treats_zero_transit_as_one_day() -> None:
    assert balanced_score(option("A", "100", 0), D("100"), 0) == D("1")
