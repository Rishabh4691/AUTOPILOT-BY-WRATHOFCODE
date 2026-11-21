from collections.abc import Mapping
from decimal import Decimal

from core.contracts import Breakdown
from core.pricing.money import CurrencyError, add_all
from core.pricing.tariff import LanePrice

FUEL = "fuel"
SECURITY = "security"


def all_in_total(
    option_total: Decimal,
    option_currency: str,
    pickup_total: Decimal | None,
    pickup_currency: str | None,
    target_currency: str,
    fx_eur_per_unit: Mapping[str, Decimal],
) -> Decimal:
    amounts = [(option_total, option_currency)]
    if pickup_total is not None:
        if pickup_currency is None:
            raise CurrencyError("pickup price has no currency")
        amounts.append((pickup_total, pickup_currency))
    return add_all(amounts, target_currency, fx_eur_per_unit)


def surcharge(lane: LanePrice, name: str) -> Decimal:
    return sum((amount for key, amount in lane.surcharges if key == name), Decimal("0"))


def build_breakdown(
    lane: LanePrice,
    chargeable_kg: Decimal,
    pickup: Decimal = Decimal("0"),
    fx_note: str | None = None,
) -> Breakdown:
    fuel = surcharge(lane, FUEL)
    security = surcharge(lane, SECURITY)
    return Breakdown(
        chargeable_kg=chargeable_kg,
        freight=lane.freight,
        fuel=fuel,
        security=security,
        other_surcharges=lane.surcharges_total - fuel - security,
        fees=lane.fees_total,
        pickup=pickup,
        fx_note=fx_note,
    )
