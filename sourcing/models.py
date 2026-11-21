"""Shared data shapes for the sourcing layer (Aryan's part).

Flow: Aditi's extractor turns an RFQ mail into a `Shipment`. The sourcing
layer turns a `Shipment` into a list of `PriceOption`s (sheets, portal, bids).
Amaan's orchestrator picks one option and quotes it.

Money is always `Decimal`, never float.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------
# Input: what an RFQ asks for
# --------------------------------------------------------------------------


class Piece(BaseModel):
    """One line of the packing list: `count` identical pieces."""

    count: int = 1
    length: Decimal
    width: Decimal
    height: Decimal
    dim_unit: Literal["cm", "in"] = "cm"
    weight: Decimal | None = None  # weight of ONE piece, if the mail gives it
    weight_unit: Literal["kg", "lb"] = "kg"


class Shipment(BaseModel):
    """The part of an RFQ the price sources need."""

    rfq_id: str
    origin: str  # IATA airport code, e.g. "ZRH"
    destination: str  # IATA airport code
    pieces: list[Piece] = Field(default_factory=list)
    gross_weight: Decimal | None = None  # TOTAL gross; None -> sum of pieces
    weight_unit: Literal["kg", "lb"] = "kg"
    volume_cbm: Decimal | None = None  # only if the mail gives volume, not dims
    preference: Literal["cheapest", "fastest"] = "cheapest"
    door_pickup: bool = False  # door-to-port: add a trucker pickup leg
    pickup_zone: str | None = None
    pickup_postcode: str | None = None
    lithium_un3480: bool = False  # batteries packed alone: cargo aircraft only
    ready_date: date | None = None
    quote_currency: str | None = None  # currency the customer wants, if any


# --------------------------------------------------------------------------
# Tariffs: what data/tariffs.json holds (one entry per airline rate sheet)
# --------------------------------------------------------------------------

SurchargeBasis = Literal[
    "per_kg",  # per chargeable kg (fuel, security usually)
    "per_kg_gross",  # per gross kg (rare)
    "flat",  # once per shipment (AWB fee, handling)
    "percent_freight",  # % of the freight line
]


class Surcharge(BaseModel):
    code: str  # e.g. "FSC", "SSC", "AWB"
    name: str = ""
    basis: SurchargeBasis
    amount: Decimal  # per kg, flat amount, or percent (15 = 15 %)
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None


class Break(BaseModel):
    """Rate per kg from `from_kg` up to the next break. N = from 0, then 45, 100..."""

    from_kg: Decimal
    rate_per_kg: Decimal


class TariffLane(BaseModel):
    origin: str
    destination: str
    breaks: list[Break]
    min_charge: Decimal = Decimal("0")  # "M": freight is never below this
    transit_days: int | None = None
    surcharges: list[Surcharge] = Field(default_factory=list)  # lane-only extras


class Tariff(BaseModel):
    tariff_id: str  # e.g. "PL-2026-11"
    airline_code: str
    airline: str
    currency: str
    valid_from: date | None = None
    valid_to: date | None = None
    lanes: list[TariffLane]
    surcharges: list[Surcharge] = Field(default_factory=list)  # apply to all lanes
    transit_days: int | None = None  # default when a lane has none
    # Volume weight: "1 cbm = 167 kg" -> kg_per_cbm=167 (every kit sheet and the
    # portal). A sheet using a divisor instead sets cm3_per_kg (e.g. 6000).
    # Neither set -> 167 kg per cbm.
    cm3_per_kg: Decimal | None = None
    kg_per_cbm: Decimal | None = None
    weight_rounding_kg: Decimal = Decimal("0.5")
    # Which weight per-kg surcharges use when we bill at a higher break:
    # "billed" = the break weight (how the portal prices the weight you ask
    # for), "chargeable" = the real chargeable weight.
    surcharge_weight: Literal["billed", "chargeable"] = "billed"
    max_piece_height_cm: Decimal | None = None  # e.g. 160 for belly-only
    accepts_un3480: bool | None = None  # None = sheet says nothing
    source_file: str | None = None
    notes: list[str] = Field(default_factory=list)


class TariffFile(BaseModel):
    generated_at: datetime | None = None
    tariffs: list[Tariff] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Output: one priced option from any source
# --------------------------------------------------------------------------


class ChargeLine(BaseModel):
    code: str
    name: str
    basis: str
    quantity: Decimal | None = None
    rate: Decimal | None = None
    amount: Decimal


class PriceOption(BaseModel):
    source: Literal["sheet", "portal", "bid"]
    leg: Literal["air", "pickup"] = "air"  # pickup = trucker, door to airport
    airline_code: str | None = None
    airline: str | None = None
    carrier_email: str | None = None
    origin: str
    destination: str
    chargeable_weight_kg: Decimal | None = None
    billed_weight_kg: Decimal | None = None  # > chargeable when a higher break is cheaper
    total: Decimal  # all-in for this leg, in `currency`
    currency: str
    total_eur: Decimal | None = None  # for comparing across currencies
    transit_days: int | None = None
    lines: list[ChargeLine] = Field(default_factory=list)
    rate_id: str | None = None  # portal only: book with it
    rate_query: dict | None = None  # portal only: params to fetch a fresh rate
    valid_until: datetime | None = None
    tariff_id: str | None = None
    dataset_version: str | None = None
    fetched_at: datetime | None = None
    notes: list[str] = Field(default_factory=list)
