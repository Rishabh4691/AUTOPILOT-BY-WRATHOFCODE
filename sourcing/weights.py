"""Weights and volumes. Most wrong prices come from here, so keep it exact.

Rules (from the battle plan cheat sheet):
- Volume weight: sum of pieces x L x W x H over every line FIRST, then convert
  once. Every start-kit sheet and the portal say 1 cbm = 167 kg, so that is
  the default (the classic cm3 / 6000 would be 166.67 kg per cbm).
- Chargeable weight: max(gross, volume weight), rounded UP to the next 0.5 kg.
- 1 lb = 0.45359237 kg, 1 in = 2.54 cm.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from .models import Piece, Shipment

LB_TO_KG = Decimal("0.45359237")
IN_TO_CM = Decimal("2.54")
CM3_PER_CBM = Decimal("1000000")
IATA_CM3_PER_KG = Decimal("6000")
PORTAL_KG_PER_CBM = Decimal("167")
CENT = Decimal("0.01")


def D(value) -> Decimal:
    """Decimal from int/str/float/Decimal without float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def money(value) -> Decimal:
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def to_kg(value, unit: str = "kg") -> Decimal:
    v = D(value)
    return v * LB_TO_KG if unit == "lb" else v


def to_cm(value, unit: str = "cm") -> Decimal:
    v = D(value)
    return v * IN_TO_CM if unit == "in" else v


def round_up(value, step="0.5") -> Decimal:
    """Round UP to the next multiple of `step` (0.5 kg by default)."""
    v, s = D(value), D(step)
    if s <= 0:
        return v
    return (v / s).to_integral_value(rounding=ROUND_CEILING) * s


def piece_volume_cm3(p: Piece) -> Decimal:
    return (
        D(p.count)
        * to_cm(p.length, p.dim_unit)
        * to_cm(p.width, p.dim_unit)
        * to_cm(p.height, p.dim_unit)
    )


def total_volume_cm3(s: Shipment) -> Decimal:
    if s.pieces:
        return sum((piece_volume_cm3(p) for p in s.pieces), Decimal("0"))
    if s.volume_cbm is not None:
        return D(s.volume_cbm) * CM3_PER_CBM
    return Decimal("0")


def total_volume_cbm(s: Shipment) -> Decimal:
    return total_volume_cm3(s) / CM3_PER_CBM


def gross_weight_kg(s: Shipment) -> Decimal:
    """Total gross weight. Prefer the stated total; else sum the pieces."""
    if s.gross_weight is not None:
        return to_kg(s.gross_weight, s.weight_unit)
    total = Decimal("0")
    for p in s.pieces:
        if p.weight is not None:
            total += D(p.count) * to_kg(p.weight, p.weight_unit)
    return total


def max_piece_height_cm(s: Shipment) -> Decimal | None:
    if not s.pieces:
        return None
    return max(to_cm(p.height, p.dim_unit) for p in s.pieces)


def volume_weight_kg(
    volume_cm3: Decimal,
    cm3_per_kg: Decimal | None = None,
    kg_per_cbm: Decimal | None = None,
) -> Decimal:
    """kg_per_cbm wins, then cm3_per_kg. With neither: 1 cbm = 167 kg, the rule
    of every start-kit sheet and the portal (the classic /6000 is 166.67)."""
    if kg_per_cbm is not None:
        return volume_cm3 / CM3_PER_CBM * D(kg_per_cbm)
    if cm3_per_kg is not None:
        return volume_cm3 / D(cm3_per_kg)
    return volume_cm3 / CM3_PER_CBM * PORTAL_KG_PER_CBM


def chargeable_weight_kg(
    s: Shipment,
    cm3_per_kg: Decimal | None = None,
    kg_per_cbm: Decimal | None = None,
    step="0.5",
) -> Decimal:
    gross = gross_weight_kg(s)
    vol = volume_weight_kg(total_volume_cm3(s), cm3_per_kg, kg_per_cbm)
    return round_up(max(gross, vol), step)


def density_kg_per_cbm(s: Shipment) -> Decimal | None:
    cbm = total_volume_cbm(s)
    if cbm <= 0:
        return None
    return gross_weight_kg(s) / cbm


def sanity_problems(s: Shipment) -> list[str]:
    """Cheap checks that catch unit mix-ups before we quote (hold for a human)."""
    problems: list[str] = []
    gross = gross_weight_kg(s)
    if gross <= 0:
        problems.append("no gross weight")
    dens = density_kg_per_cbm(s)
    if dens is not None and not (Decimal("20") <= dens <= Decimal("1000")):
        problems.append(
            f"density {dens:.0f} kg/m3 is outside 20-1000: check lb/kg or in/cm"
        )
    for code in (s.origin, s.destination):
        if not (len(code) == 3 and code.isalpha() and code.isupper()):
            problems.append(f"'{code}' is not an IATA airport code")
    return problems
