from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from decimal import Decimal

from core.contracts import RFQ, Breakdown, PriceOption
from sourcing.models import Piece as SourcingPiece
from sourcing.models import PriceOption as SheetOption
from sourcing.models import Shipment
from sourcing.sheets import get_sheet_prices

log = logging.getLogger("core.sheets")

CENT = Decimal("0.01")
FREIGHT = ("freight", "air", "base", "rate")
FUEL = ("fuel", "fsc", "myc")
SECURITY = ("security", "sec", "ssc", "xray")


def to_shipment(rfq: RFQ) -> Shipment:
    return Shipment(
        rfq_id=str(rfq.mail_id),
        origin=rfq.origin,
        destination=rfq.destination,
        pieces=[
            SourcingPiece(
                count=p.count,
                length=p.length_cm,
                width=p.width_cm,
                height=p.height_cm,
                weight=p.weight_kg,
            )
            for p in rfq.pieces
        ],
        gross_weight=rfq.gross_kg,
        volume_cbm=rfq.volume_cbm,
        preference=rfq.preference.value,
        door_pickup=rfq.door_pickup,
        pickup_zone=rfq.pickup_zone,
        ready_date=rfq.ready_date,
    )


def breakdown(opt: SheetOption, rate: Decimal) -> Breakdown:
    parts = {
        "freight": Decimal("0"),
        "fuel": Decimal("0"),
        "security": Decimal("0"),
        "other": Decimal("0"),
    }
    for line in opt.lines:
        key = f"{line.code} {line.name}".lower()
        bucket = (
            "freight"
            if any(w in key for w in FREIGHT) and not any(w in key for w in FUEL + SECURITY)
            else "fuel"
            if any(w in key for w in FUEL)
            else "security"
            if any(w in key for w in SECURITY)
            else "other"
        )
        parts[bucket] += line.amount * rate
    return Breakdown(
        chargeable_kg=opt.billed_weight_kg or opt.chargeable_weight_kg or Decimal("0"),
        freight=parts["freight"].quantize(CENT),
        fuel=parts["fuel"].quantize(CENT),
        security=parts["security"].quantize(CENT),
        fees=parts["other"].quantize(CENT),
        fx_note=None if opt.currency == "EUR" else f"converted from {opt.total} {opt.currency}",
    )


def convert(opt: SheetOption) -> PriceOption | None:
    if opt.leg != "air" or opt.transit_days is None:
        return None
    if opt.currency == "EUR":
        total, rate = opt.total, Decimal("1")
    elif opt.total_eur is not None and opt.total:
        total, rate = opt.total_eur, opt.total_eur / opt.total
    else:
        return None
    return PriceOption(
        source="sheet",
        carrier=opt.airline or opt.airline_code or "airline",
        carrier_code=opt.airline_code,
        total=total.quantize(CENT),
        currency="EUR",
        transit_days=opt.transit_days,
        breakdown=breakdown(opt, rate),
    )


class SheetPriceSource:
    name = "sheets"

    async def quote(self, rfq: RFQ) -> list[PriceOption]:
        shipment = to_shipment(rfq)
        if rfq.ready_date is not None:
            # A sheet only counts if it is valid on the departure day; no fallback to today.
            departure = rfq.ready_date + timedelta(days=1 if rfq.door_pickup else 0)
            options = await asyncio.to_thread(get_sheet_prices, shipment, None, departure)
        else:
            options = await asyncio.to_thread(get_sheet_prices, shipment)
        out = [o for o in (convert(x) for x in options) if o is not None]
        log.info(
            "sheet_prices", extra={"rfq": rfq.mail_id, "found": len(options), "usable": len(out)}
        )
        return out
