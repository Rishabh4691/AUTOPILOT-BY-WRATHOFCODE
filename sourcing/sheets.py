"""Prices from the airline rate sheets (data/tariffs.json).

get_sheet_prices(rfq) -> every matching option, cheapest first.

Per lane:
  chargeable = max(gross, volume weight), rounded up to 0.5 kg (per sheet rules)
  freight    = max(minimum charge, billed weight x rate of that weight's bracket)
  We also try every HIGHER break: 995 kg at 2.10 = 2,089.50 but 1,000 kg at
  1.85 = 1,850.00, so we bill as 1,000 kg. The cheapest total wins.
  + surcharges: per kg, per gross kg, flat, or % of freight (each sheet's list)
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from . import fx
from .models import Break, ChargeLine, PriceOption, Shipment, Surcharge, Tariff, TariffLane
from .tariffs import TariffStore
from .weights import (
    chargeable_weight_kg,
    gross_weight_kg,
    max_piece_height_cm,
    money,
)

_default_store: TariffStore | None = None


def _store() -> TariffStore:
    global _default_store
    if _default_store is None:
        _default_store = TariffStore()
    else:
        _default_store.reload_if_changed()
    return _default_store


def _as_shipment(rfq) -> Shipment:
    return rfq if isinstance(rfq, Shipment) else Shipment.model_validate(rfq)


def rate_for_weight(breaks: list[Break], weight: Decimal) -> Decimal | None:
    """Rate of the bracket that `weight` falls in (bracket runs to the next break)."""
    rate = None
    for b in sorted(breaks, key=lambda b: b.from_kg):
        if weight >= b.from_kg:
            rate = b.rate_per_kg
    return rate


def _surcharge_line(sc: Surcharge, freight: Decimal, per_kg_weight: Decimal, gross: Decimal) -> ChargeLine:
    if sc.basis == "per_kg":
        qty, amount = per_kg_weight, per_kg_weight * sc.amount
    elif sc.basis == "per_kg_gross":
        qty, amount = gross, gross * sc.amount
    elif sc.basis == "percent_freight":
        qty, amount = freight, freight * sc.amount / Decimal("100")
    else:  # flat
        qty, amount = None, sc.amount
    if sc.min_amount is not None:
        amount = max(amount, sc.min_amount)
    if sc.max_amount is not None:
        amount = min(amount, sc.max_amount)
    return ChargeLine(
        code=sc.code,
        name=sc.name or sc.code,
        basis=sc.basis,
        quantity=qty,
        rate=sc.amount,
        amount=money(amount),
    )


def price_lane(tariff: Tariff, lane: TariffLane, s: Shipment) -> PriceOption | None:
    """Cheapest way to bill this shipment on this lane, or None if no rate fits."""
    cw = chargeable_weight_kg(s, tariff.cm3_per_kg, tariff.kg_per_cbm, tariff.weight_rounding_kg)
    gross = gross_weight_kg(s)
    breaks = sorted(lane.breaks, key=lambda b: b.from_kg)

    candidates: list[tuple[Decimal, Decimal]] = []
    own_rate = rate_for_weight(breaks, cw)
    if own_rate is not None:
        candidates.append((cw, own_rate))
    candidates += [(b.from_kg, b.rate_per_kg) for b in breaks if b.from_kg > cw]
    if not candidates:
        return None

    best: PriceOption | None = None
    for billed, rate in candidates:
        raw = billed * rate
        freight = money(max(lane.min_charge, raw))
        at_minimum = lane.min_charge > raw
        lines = [
            ChargeLine(
                code="FRT",
                name="Air freight" + (" (minimum charge)" if at_minimum else ""),
                basis="minimum" if at_minimum else "per_kg",
                quantity=None if at_minimum else billed,
                rate=None if at_minimum else rate,
                amount=freight,
            )
        ]
        per_kg_weight = billed if tariff.surcharge_weight == "billed" else cw
        for sc in [*tariff.surcharges, *lane.surcharges]:
            lines.append(_surcharge_line(sc, freight, per_kg_weight, gross))
        total = money(sum((l.amount for l in lines), Decimal("0")))

        notes = []
        if billed > cw:
            notes.append(
                f"billed as {billed} kg (break) at {rate}/kg: cheaper than "
                f"{cw} kg at {own_rate}/kg"
            )
        if at_minimum:
            notes.append(f"minimum charge {lane.min_charge} {tariff.currency} applies")

        option = PriceOption(
            source="sheet",
            airline_code=tariff.airline_code,
            airline=tariff.airline,
            origin=s.origin,
            destination=s.destination,
            chargeable_weight_kg=cw,
            billed_weight_kg=billed,
            total=total,
            currency=tariff.currency,
            total_eur=fx.to_eur(total, tariff.currency),
            transit_days=lane.transit_days if lane.transit_days is not None else tariff.transit_days,
            lines=lines,
            valid_until=(
                datetime.combine(tariff.valid_to, datetime.max.time(), tzinfo=UTC)
                if tariff.valid_to
                else None
            ),
            tariff_id=tariff.tariff_id,
            fetched_at=datetime.now(UTC),
            notes=notes,
        )
        if best is None or option.total < best.total:
            best = option
    return best


def _ineligible(tariff: Tariff, s: Shipment) -> str | None:
    h = max_piece_height_cm(s)
    if tariff.max_piece_height_cm is not None and h is not None and h > tariff.max_piece_height_cm:
        return f"{tariff.airline_code}: piece height {h} cm > {tariff.max_piece_height_cm} cm"
    if s.lithium_un3480 and tariff.accepts_un3480 is False:
        return f"{tariff.airline_code}: does not take UN3480 lithium batteries"
    return None


def sheet_options(rfq, tariffs: list[Tariff] | None = None, on: date | None = None):
    """(options cheapest first, reasons for skipped tariffs)."""
    s = _as_shipment(rfq)
    tariffs = tariffs if tariffs is not None else _store().active(on)
    options: list[PriceOption] = []
    skipped: list[str] = []
    origin, dest = s.origin.upper(), s.destination.upper()
    for t in tariffs:
        lanes = [
            l
            for l in t.lanes
            if l.origin.upper() in (origin, "*") and l.destination.upper() == dest
        ]
        if not lanes:
            continue
        why = _ineligible(t, s)
        if why:
            skipped.append(why)
            continue
        for lane in lanes:
            opt = price_lane(t, lane, s)
            if opt:
                options.append(opt)
            else:
                skipped.append(f"{t.airline_code}: no weight break covers this weight")
    options.sort(key=lambda o: (o.total_eur is None, o.total_eur or o.total))
    return options, skipped


def get_sheet_prices(rfq, tariffs: list[Tariff] | None = None, on: date | None = None) -> list[PriceOption]:
    """Every matching option from the rate sheets, cheapest first (EUR-compared)."""
    return sheet_options(rfq, tariffs, on)[0]
