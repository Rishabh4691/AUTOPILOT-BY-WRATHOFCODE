"""Sourcing layer (owner: Aryan): every price source + booking + tariff ingestion.

    from sourcing import Shipment, get_sheet_prices, PortalClient, get_portal_options

    s = Shipment(rfq_id="RFQ-1", origin="ZRH", destination="JFK",
                 pieces=[{"count": 2, "length": 120, "width": 80, "height": 100, "weight": 150}])
    sheet = get_sheet_prices(s)                                   # list[PriceOption]
    async with PortalClient() as portal:
        portal_opts, notes = await get_portal_options(s, portal)
"""

from .booking import BookingResult, book_option, parse_booking_confirmation
from .bids import (
    BidQuote,
    BidTracker,
    Carrier,
    bid_option,
    bid_ref,
    bid_request_email,
    carriers_for,
    parse_bid_reply,
)
from .ingest import ingest_tariff_mail, is_tariff_mail, parse_tariff_file, validate_tariff
from .models import ChargeLine, Piece, PriceOption, Shipment, Tariff, TariffLane
from .portal import PortalClient, get_portal_options
from .sheets import get_sheet_prices, sheet_options
from .tariffs import TariffStore
from .weights import chargeable_weight_kg, sanity_problems
from . import kit_parsers  # noqa: E402,F401  registers the rate-sheet parser for ingest

__all__ = [
    "BidQuote",
    "BidTracker",
    "BookingResult",
    "Carrier",
    "ChargeLine",
    "Piece",
    "PortalClient",
    "PriceOption",
    "Shipment",
    "Tariff",
    "TariffLane",
    "TariffStore",
    "bid_option",
    "bid_ref",
    "bid_request_email",
    "book_option",
    "carriers_for",
    "chargeable_weight_kg",
    "get_portal_options",
    "get_sheet_prices",
    "ingest_tariff_mail",
    "is_tariff_mail",
    "parse_bid_reply",
    "parse_booking_confirmation",
    "parse_tariff_file",
    "sanity_problems",
    "sheet_options",
    "validate_tariff",
]
