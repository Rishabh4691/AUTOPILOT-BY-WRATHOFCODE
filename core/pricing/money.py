from collections.abc import Iterable, Mapping
from decimal import Decimal

from core.contracts import to_money

BASE_CURRENCY = "EUR"


class CurrencyError(ValueError):
    pass


def eur_per_unit(currency: str, fx_eur_per_unit: Mapping[str, Decimal]) -> Decimal:
    code = currency.upper()
    if code == BASE_CURRENCY:
        return Decimal("1")
    rate = fx_eur_per_unit.get(code)
    if rate is None or rate <= 0:
        raise CurrencyError(f"no exchange rate for {code}")
    return rate


def convert(
    amount: Decimal, from_ccy: str, to_ccy: str, fx_eur_per_unit: Mapping[str, Decimal]
) -> Decimal:
    if from_ccy.upper() == to_ccy.upper():
        return to_money(amount)
    eur = amount * eur_per_unit(from_ccy, fx_eur_per_unit)
    return to_money(eur / eur_per_unit(to_ccy, fx_eur_per_unit))


def add_all(
    amounts: Iterable[tuple[Decimal, str]], target: str, fx_eur_per_unit: Mapping[str, Decimal]
) -> Decimal:
    converted = (convert(amount, ccy, target, fx_eur_per_unit) for amount, ccy in amounts)
    return to_money(sum(converted, Decimal("0")))
