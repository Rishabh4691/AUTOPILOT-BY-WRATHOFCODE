from decimal import Decimal

import pytest

from mail.extract import extract

BASE = (
    "Could you please quote the fastest air freight option from HAM to SGN? We deliver to Hamburg airport "
    "ourselves. {x} Please send the all-in price in EUR."
)


@pytest.mark.parametrize(
    "text,gross,volume,dim_unit",
    [
        ("3 pieces, 1413.17 lb gross, 95.00 cubic feet.", Decimal("1413.17"), Decimal("2.6900960"), None),
        ("3 pieces, 641 kg gross, 95 cu ft.", Decimal("641"), Decimal("2.6900960"), None),
        ("3 pieces, 641 kg gross, 95 ft³.", Decimal("641"), Decimal("2.6900960"), None),
        ("3 pieces, 1.2 metric tons, 2.69 cbm.", Decimal("1200"), Decimal("2.69"), None),
        ("3 pieces, 0.7 short tons, 2.69 cbm.", Decimal("635.029318"), Decimal("2.69"), None),
        ("3 pieces, 641000 g gross, 2.69 cbm.", Decimal("641"), Decimal("2.69"), None),
        ("3 pieces, 641 kg, volume 2690 litres.", Decimal("641"), Decimal("2.69"), None),
        ('3 pallets, 48" x 40" x 50", 641 kg gross.', Decimal("641"), None, "in"),
        ("3 pallets, 48″ x 40″ x 50″, 641 kg gross.", Decimal("641"), None, "in"),
        ("3 pieces of 48 x 40 x 50 inches each, 641 kg total.", Decimal("641"), None, "in"),
        ("3 pieces of 120 x 100 x 110 cm each, 641 kg total.", Decimal("641"), None, "cm"),
    ],
)
def test_units(text, gross, volume, dim_unit):
    shipment = extract("Air freight quote: HAM to SGN", BASE.format(x=text), "a@b.c", "1").shipment
    assert shipment is not None
    assert Decimal(shipment.gross_weight) == gross
    assert (shipment.volume_cbm is None and volume is None) or Decimal(shipment.volume_cbm) == volume
    assert (dim_unit is None and not shipment.pieces) or shipment.pieces[0].dim_unit == dim_unit


def test_each_gross_stays_per_piece():
    text = "3 Paletten, je 120 x 80 x 110 cm, je 210 kg brutto."
    shipment = extract("Anfrage HAM DXB", BASE.format(x=text), "a@b.c", "1").shipment
    assert shipment.pieces[0].weight == Decimal("210")
