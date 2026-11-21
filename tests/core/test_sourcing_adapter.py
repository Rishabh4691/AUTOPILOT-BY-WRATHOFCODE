from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from core.agents.sourcing_adapter import (
    UNKNOWN_TRANSIT_DAYS,
    SheetPriceSource,
    SourcingPortalPriceSource,
    to_option,
    to_shipment,
)
from core.config import load_settings
from core.contracts import RFQ, Piece, Preference, SourceUnavailable
from sourcing import PriceOption as SourcingOption

NOW = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)


def rfq(origin: str = "FRA", destination: str = "ORD") -> RFQ:
    return RFQ(
        mail_id=102,
        thread_root_id=102,
        customer="buyer@example.com",
        subject="RFQ",
        origin=origin,
        destination=destination,
        pieces=(
            Piece(count=3, length_cm=Decimal(100), width_cm=Decimal(80), height_cm=Decimal(60)),
        ),
        gross_kg=Decimal("410"),
        door_pickup=False,
        preference=Preference.CHEAPEST,
        preference_assumed=False,
        received_at=NOW,
    )


def test_rfq_maps_to_shipment() -> None:
    shipment = to_shipment(rfq())
    assert shipment.origin == "FRA"
    assert shipment.gross_weight == Decimal("410")
    assert shipment.pieces[0].count == 3
    assert shipment.preference == "cheapest"


def test_option_without_transit_gets_sentinel() -> None:
    option = SourcingOption(
        source="sheet",
        origin="FRA",
        destination="ORD",
        total=Decimal("100.005"),
        currency="EUR",
        airline="Test Air",
    )
    converted = to_option(option, NOW)
    assert converted.transit_days == UNKNOWN_TRANSIT_DAYS
    assert converted.total == Decimal("100.01")
    assert converted.rate_id_at is None


async def test_sheets_price_fra_ord_from_the_kit_tariffs() -> None:
    options = await SheetPriceSource(lambda: NOW).quote(rfq())
    by_carrier = {o.carrier: o for o in options}
    assert by_carrier["Yellowtail Air Freight"].total == Decimal("1061.90")
    assert by_carrier["Yellowtail Air Freight"].currency == "EUR"


@respx.mock
async def test_portal_without_lane_is_unavailable() -> None:
    settings = load_settings(environ={"FIVEU_API_KEY": "test-key"})
    respx.get(f"{settings.base_url}/v1/portal/ports").mock(
        return_value=httpx.Response(200, json={"lanes": []})
    )
    source = SourcingPortalPriceSource(settings, lambda: NOW)
    with pytest.raises(SourceUnavailable):
        await source.quote(rfq())
    await source.aclose()
