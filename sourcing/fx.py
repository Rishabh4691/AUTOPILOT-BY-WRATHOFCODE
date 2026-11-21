"""Currency conversion, only to COMPARE options. A quote states one currency.

Rates are EUR per 1 unit of the currency (the portal's `fx_eur_per_usd`
field uses the same direction). The portal sends a rate with every non-EUR
price; we remember the latest one so sheets in that currency can be compared.
Set a starting table with FX_EUR_PER (e.g. "USD=0.92,CHF=1.06") in .env, or
from the start kit if it ships one.
"""

from __future__ import annotations

import os
from decimal import Decimal

from .weights import D, money

_rates: dict[str, Decimal] = {"EUR": Decimal("1")}


def _load_env() -> None:
    raw = os.getenv("FX_EUR_PER", "")
    for part in raw.split(","):
        if "=" in part:
            cur, val = part.split("=", 1)
            set_rate(cur.strip(), val.strip())


def set_rate(currency: str, eur_per_unit) -> None:
    _rates[currency.upper()] = D(eur_per_unit)


def get_rate(currency: str) -> Decimal | None:
    return _rates.get(currency.upper())


def to_eur(amount, currency: str) -> Decimal | None:
    rate = get_rate(currency)
    if rate is None:
        return None
    return money(D(amount) * rate)


def from_eur(amount_eur, currency: str) -> Decimal | None:
    rate = get_rate(currency)
    if rate is None or rate == 0:
        return None
    return money(D(amount_eur) / rate)


def known() -> dict[str, Decimal]:
    return dict(_rates)


_load_env()
