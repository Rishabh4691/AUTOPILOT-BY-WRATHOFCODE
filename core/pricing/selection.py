from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from core.contracts import Preference
from core.pricing.money import CurrencyError

HALF = Decimal("0.5")


class SelectionError(ValueError):
    pass


class Priced(Protocol):
    @property
    def carrier(self) -> str: ...

    @property
    def total(self) -> Decimal: ...

    @property
    def currency(self) -> str: ...

    @property
    def transit_days(self) -> int: ...


def _check(options: Sequence[Priced]) -> None:
    if not options:
        raise SelectionError("no options to choose from")
    if len({option.currency for option in options}) > 1:
        raise CurrencyError("options are in different currencies")


def select[T: Priced](options: Sequence[T], preference: Preference) -> T:
    _check(options)
    if preference is Preference.FASTEST:
        return min(options, key=lambda o: (o.transit_days, o.total, o.carrier))
    return min(options, key=lambda o: (o.total, o.transit_days, o.carrier))


def balanced_score(
    option: Priced,
    min_price: Decimal,
    min_transit: int,
    price_weight: Decimal = HALF,
    transit_weight: Decimal = HALF,
) -> Decimal:
    if min_price <= 0:
        raise SelectionError("minimum price must be positive")
    transit_ratio = Decimal(max(option.transit_days, 1)) / Decimal(max(min_transit, 1))
    return price_weight * option.total / min_price + transit_weight * transit_ratio


def select_balanced[T: Priced](
    options: Sequence[T], price_weight: Decimal = HALF, transit_weight: Decimal = HALF
) -> T:
    _check(options)
    min_price = min(option.total for option in options)
    min_transit = min(option.transit_days for option in options)

    def score(option: T) -> tuple[Decimal, Decimal, str]:
        value = balanced_score(option, min_price, min_transit, price_weight, transit_weight)
        return value, option.total, option.carrier

    return min(options, key=score)
