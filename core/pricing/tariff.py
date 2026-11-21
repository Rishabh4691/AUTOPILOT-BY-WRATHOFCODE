from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

from core.contracts import to_money

Break = tuple[Decimal, Decimal]
Named = tuple[str, Decimal]


class TariffError(ValueError):
    pass


@dataclass(frozen=True)
class LaneTariff:
    airline: str
    origin: str
    destination: str
    currency: str
    transit_days: int
    minimum: Decimal
    breaks: tuple[Break, ...]
    surcharges_per_kg: tuple[Named, ...] = ()
    flat_fees: tuple[Named, ...] = ()


@dataclass(frozen=True)
class LanePrice:
    billed_kg: Decimal
    rate: Decimal
    freight: Decimal
    surcharges: tuple[Named, ...]
    surcharges_total: Decimal
    fees: tuple[Named, ...]
    fees_total: Decimal
    total: Decimal
    currency: str


def validate(tariff: LaneTariff) -> None:
    if not tariff.breaks:
        raise TariffError("tariff has no weight breaks")
    thresholds = [threshold for threshold, _ in tariff.breaks]
    if thresholds[0] != 0:
        raise TariffError("first weight break must start at 0 kg")
    if any(a >= b for a, b in pairwise(thresholds)):
        raise TariffError("weight breaks must be strictly ascending")
    if any(rate <= 0 for _, rate in tariff.breaks):
        raise TariffError("weight break rates must be positive")
    if tariff.minimum < 0:
        raise TariffError("minimum charge must not be negative")


def rate_for(breaks: tuple[Break, ...], kg: Decimal) -> Decimal:
    return [rate for threshold, rate in breaks if threshold <= kg][-1]


def next_break(breaks: tuple[Break, ...], kg: Decimal) -> Decimal | None:
    return next((threshold for threshold, _ in breaks if threshold > kg), None)


def _sum(amounts: tuple[Named, ...]) -> Decimal:
    return to_money(sum((amount for _, amount in amounts), Decimal("0")))


def price_at(tariff: LaneTariff, billed_kg: Decimal) -> LanePrice:
    rate = rate_for(tariff.breaks, billed_kg)
    freight = to_money(max(tariff.minimum, billed_kg * rate))
    surcharges = tuple(
        (name, to_money(billed_kg * per_kg)) for name, per_kg in tariff.surcharges_per_kg
    )
    fees = tuple((name, to_money(amount)) for name, amount in tariff.flat_fees)
    surcharges_total = _sum(surcharges)
    fees_total = _sum(fees)
    return LanePrice(
        billed_kg=billed_kg,
        rate=rate,
        freight=freight,
        surcharges=surcharges,
        surcharges_total=surcharges_total,
        fees=fees,
        fees_total=fees_total,
        total=to_money(freight + surcharges_total + fees_total),
        currency=tariff.currency,
    )


def price_lane(
    tariff: LaneTariff, chargeable_kg: Decimal, test_next_break: bool = True
) -> LanePrice:
    validate(tariff)
    if chargeable_kg <= 0:
        raise TariffError("chargeable weight must be positive")
    actual = price_at(tariff, chargeable_kg)
    upper = next_break(tariff.breaks, chargeable_kg) if test_next_break else None
    if upper is None:
        return actual
    bumped = price_at(tariff, upper)
    return bumped if bumped.total < actual.total else actual
