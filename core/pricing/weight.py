from collections.abc import Iterable
from decimal import ROUND_CEILING, Decimal

from core.contracts import Piece

VOLUME_KG_PER_CBM = Decimal("167")
CM3_PER_CBM = Decimal("1000000")
WEIGHT_STEP = Decimal("0.1")


def volume_cbm(pieces: Iterable[Piece]) -> Decimal:
    cm3 = sum(
        (Decimal(p.count) * p.length_cm * p.width_cm * p.height_cm for p in pieces),
        Decimal("0"),
    )
    return cm3 / CM3_PER_CBM


def volume_kg(cbm: Decimal, factor: Decimal = VOLUME_KG_PER_CBM) -> Decimal:
    return cbm * factor


def round_up_half_kg(kg: Decimal) -> Decimal:
    doubled = (kg * 2).to_integral_value(rounding=ROUND_CEILING)
    return (doubled / 2).quantize(WEIGHT_STEP)


def chargeable_kg(
    gross_kg: Decimal,
    pieces: Iterable[Piece] = (),
    cbm: Decimal | None = None,
    factor: Decimal = VOLUME_KG_PER_CBM,
) -> Decimal:
    piece_list = tuple(pieces)
    total_cbm = volume_cbm(piece_list) if piece_list else (cbm or Decimal("0"))
    return round_up_half_kg(max(gross_kg, volume_kg(total_cbm, factor)))
