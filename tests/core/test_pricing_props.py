from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from core.contracts import Preference, PriceOption
from core.pricing.selection import select
from core.pricing.tariff import LaneTariff, price_lane
from core.pricing.weight import chargeable_kg, volume_kg

D = Decimal

kgs = st.decimals(min_value=D("0.1"), max_value=D("5000"), places=2)
cbms = st.decimals(min_value=D("0"), max_value=D("30"), places=3)
rates = st.decimals(min_value=D("0.5"), max_value=D("6"), places=2)

TARIFF = LaneTariff(
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


@given(kgs, cbms)
def test_chargeable_covers_gross_and_volume(gross: Decimal, cbm: Decimal) -> None:
    result = chargeable_kg(gross, cbm=cbm)
    assert result >= gross
    assert result >= volume_kg(cbm)
    assert (result * 2) % 1 == 0


@given(kgs)
def test_next_break_never_costs_more(kg: Decimal) -> None:
    tested = price_lane(TARIFF, kg)
    untested = price_lane(TARIFF, kg, test_next_break=False)
    assert tested.total <= untested.total
    assert tested.freight >= TARIFF.minimum
    assert tested.total == tested.total.quantize(D("0.01"))
    assert tested.billed_kg >= kg


@given(
    st.lists(
        st.tuples(
            st.decimals(min_value=D("1"), max_value=D("9999"), places=2),
            st.integers(min_value=0, max_value=20),
        ),
        min_size=1,
        max_size=8,
    )
)
def test_select_cheapest_is_minimal_member(rows: list[tuple[Decimal, int]]) -> None:
    options = [
        PriceOption(source="t", carrier=f"C{i}", total=t, currency="EUR", transit_days=d)
        for i, (t, d) in enumerate(rows)
    ]
    chosen = select(options, Preference.CHEAPEST)
    assert chosen in options
    assert chosen.total == min(o.total for o in options)


@given(rates)
def test_single_break_total_matches_formula(rate: Decimal) -> None:
    tariff = LaneTariff("X", "FRA", "ORD", "EUR", 1, D("0"), ((D("0"), rate),))
    assert price_lane(tariff, D("100")).total == (rate * 100).quantize(D("0.01"))
