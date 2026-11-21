from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime

import sourcing
from core.config import Settings
from core.contracts import RFQ, Breakdown, PortalDown, PriceOption, SourceUnavailable

log = logging.getLogger("core.agents.sourcing_adapter")

UNKNOWN_TRANSIT_DAYS = 99


def to_shipment(rfq: RFQ) -> sourcing.Shipment:
    return sourcing.Shipment(
        rfq_id=str(rfq.mail_id),
        origin=rfq.origin,
        destination=rfq.destination,
        pieces=[
            sourcing.Piece(
                count=piece.count,
                length=piece.length_cm,
                width=piece.width_cm,
                height=piece.height_cm,
                weight=piece.weight_kg,
            )
            for piece in rfq.pieces
        ],
        gross_weight=rfq.gross_kg,
        volume_cbm=rfq.volume_cbm if not rfq.pieces else None,
        preference=rfq.preference.value,
        door_pickup=rfq.door_pickup,
        pickup_zone=rfq.pickup_zone,
        ready_date=rfq.ready_date,
        quote_currency=rfq.currency,
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def to_option(option: sourcing.PriceOption, now: datetime) -> PriceOption:
    carrier = option.airline or option.airline_code or option.source
    return PriceOption(
        source=option.source,
        carrier=carrier,
        carrier_code=option.airline_code,
        rate_id=option.rate_id,
        rate_id_at=(_aware(option.fetched_at) or now) if option.rate_id else None,
        valid_until=_aware(option.valid_until),
        total=option.total,
        currency=option.currency,
        transit_days=UNKNOWN_TRANSIT_DAYS if option.transit_days is None else option.transit_days,
        includes_pickup=False,
        breakdown=Breakdown(
            chargeable_kg=option.billed_weight_kg or option.chargeable_weight_kg or 0,
        ),
    )


def convert_all(
    options: Iterable[sourcing.PriceOption], now: datetime, source_name: str
) -> list[PriceOption]:
    converted: list[PriceOption] = []
    for option in options:
        if option.leg != "air":
            continue
        try:
            converted.append(to_option(option, now))
        except ValueError as error:
            log.warning(
                "option_rejected", extra={"source": source_name, "error": type(error).__name__}
            )
    return converted


class SheetPriceSource:
    name = "sheets"

    def __init__(self, now: Callable[[], datetime]) -> None:
        self.now = now

    async def quote(self, rfq: RFQ) -> list[PriceOption]:
        shipment = to_shipment(rfq)
        options = await asyncio.to_thread(sourcing.get_sheet_prices, shipment)
        return convert_all(options, self.now(), self.name)


class SourcingPortalPriceSource:
    name = "portal"

    def __init__(self, settings: Settings, now: Callable[[], datetime]) -> None:
        self.portal = sourcing.PortalClient(api_key=settings.api_key, base_url=settings.base_url)
        self.now = now
        self.last_notes: list[str] = []

    async def quote(self, rfq: RFQ) -> list[PriceOption]:
        options, notes = await sourcing.get_portal_options(to_shipment(rfq), self.portal)
        self.last_notes = list(notes)
        if notes:
            log.info("portal_notes", extra={"rfq": rfq.mail_id, "notes": notes[:5]})
        if not options and any("PortalUnavailable" in note for note in notes):
            raise PortalDown(notes[0])
        if not options:
            raise SourceUnavailable(notes[0] if notes else "portal returned no prices")
        return convert_all(options, self.now(), self.name)

    async def aclose(self) -> None:
        await self.portal.aclose()
