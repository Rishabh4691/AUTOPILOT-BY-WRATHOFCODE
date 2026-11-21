from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from core.config import Settings, auth_headers
from core.contracts import RFQ, Breakdown, PriceOption, SourceUnavailable
from core.http import HttpGiveUp, request

log = logging.getLogger("core.agents.portal")

PORTS_TTL_S = 600.0
MAX_CONCURRENCY = 4
RETRY_STATUSES = frozenset({429, 500, 502, 504})
CBM = Decimal("0.001")


class PortalAirline(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: str
    name: str


class PortalLane(BaseModel):
    model_config = ConfigDict(extra="ignore")
    origin: str
    destination: str
    airlines: list[PortalAirline]


class PortalPorts(BaseModel):
    model_config = ConfigDict(extra="ignore")
    lanes: list[PortalLane]


class PortalRate(BaseModel):
    model_config = ConfigDict(extra="allow")
    rate_id: str
    airline: str
    airline_code: str
    origin: str
    destination: str
    weight_kg: Decimal
    chargeable_weight_kg: Decimal
    total: Decimal
    currency: str
    fx_eur_per_usd: Decimal | None = None
    transit_days: int
    valid_until: datetime
    dataset_version: str | int | None = None


def shipment_volume(rfq: RFQ) -> Decimal:
    if rfq.volume_cbm is not None:
        return rfq.volume_cbm
    cubic_cm = sum(
        (p.count * p.length_cm * p.width_cm * p.height_cm for p in rfq.pieces), Decimal(0)
    )
    return (cubic_cm / Decimal(1_000_000)).quantize(CBM, rounding=ROUND_HALF_UP)


def server_message(response: httpx.Response) -> str:
    try:
        payload: Any = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(payload, dict):
        for key in ("message", "detail", "error"):
            if isinstance(payload.get(key), str):
                return str(payload[key])[:200]
    return response.text[:200]


def to_option(rate: PortalRate, now: datetime) -> PriceOption:
    fx_note = f"fx_eur_per_usd={rate.fx_eur_per_usd}" if rate.fx_eur_per_usd else None
    return PriceOption(
        source="portal",
        carrier=rate.airline,
        carrier_code=rate.airline_code,
        rate_id=rate.rate_id,
        rate_id_at=now,
        valid_until=rate.valid_until,
        total=rate.total,
        currency=rate.currency,
        transit_days=rate.transit_days,
        includes_pickup=False,
        breakdown=Breakdown(chargeable_kg=rate.chargeable_weight_kg, fx_note=fx_note),
    )


class PortalPriceSource:
    name = "portal"

    def __init__(
        self, client: httpx.AsyncClient, settings: Settings, now: Callable[[], datetime]
    ) -> None:
        self.client = client
        self.settings = settings
        self.now = now
        self.deadline_s = 30.0
        self.last_errors: list[str] = []
        self._ports: PortalPorts | None = None
        self._ports_at = 0.0
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def quote(self, rfq: RFQ) -> list[PriceOption]:
        self.last_errors = []
        deadline = time.monotonic() + self.deadline_s
        lane = await self._lane(rfq, deadline)
        results = await asyncio.gather(
            *(self._option(rfq, airline.code, deadline) for airline in lane.airlines),
            return_exceptions=True,
        )
        options = [r for r in results if isinstance(r, PriceOption)]
        outages = [r for r in results if isinstance(r, SourceUnavailable)]
        if not options and outages:
            raise outages[0]
        log.info(
            "portal_quote",
            extra={"rfq": rfq.mail_id, "options": len(options), "errors": len(self.last_errors)},
        )
        return options

    async def fresh_rate(self, option: PriceOption, rfq: RFQ) -> PriceOption:
        if not option.carrier_code:
            raise SourceUnavailable("option has no airline code")
        deadline = time.monotonic() + self.deadline_s
        result = await self._option(rfq, option.carrier_code, deadline)
        if result is None:
            raise SourceUnavailable(f"no fresh rate for {option.carrier_code}")
        return result

    async def _get(self, path: str, deadline: float, **params: str) -> httpx.Response:
        try:
            response = await request(
                self.client,
                "GET",
                f"{self.settings.base_url}{path}",
                deadline=deadline,
                retry_statuses=RETRY_STATUSES,
                params=params,
                headers=auth_headers(self.settings),
            )
        except HttpGiveUp as error:
            raise SourceUnavailable(f"portal gave up: {error.status}") from error
        if response.status_code == 503:
            raise SourceUnavailable(f"portal unavailable: {server_message(response)}")
        return response

    async def _ports_data(self, deadline: float) -> PortalPorts:
        if self._ports is not None and time.monotonic() - self._ports_at < PORTS_TTL_S:
            return self._ports
        response = await self._get("/v1/portal/ports", deadline)
        if response.status_code != 200:
            raise SourceUnavailable(f"portal ports failed with {response.status_code}")
        try:
            ports = PortalPorts.model_validate(response.json())
        except (ValidationError, ValueError) as error:
            raise SourceUnavailable("portal ports malformed") from error
        self._ports, self._ports_at = ports, time.monotonic()
        return ports

    async def _lane(self, rfq: RFQ, deadline: float) -> PortalLane:
        ports = await self._ports_data(deadline)
        for lane in ports.lanes:
            if lane.origin.upper() == rfq.origin and lane.destination.upper() == rfq.destination:
                return lane
        raise SourceUnavailable("lane not on portal")

    async def _option(self, rfq: RFQ, airline: str, deadline: float) -> PriceOption | None:
        async with self._semaphore:
            response = await self._get(
                "/v1/portal/rates",
                deadline,
                origin=rfq.origin,
                destination=rfq.destination,
                airline=airline,
                weight_kg=str(rfq.gross_kg),
                volume_cbm=str(shipment_volume(rfq)),
            )
        if response.status_code != 200:
            self._skip(airline, f"status {response.status_code}")
            return None
        try:
            rate = PortalRate.model_validate(response.json())
        except (ValidationError, ValueError) as error:
            self._skip(airline, f"malformed rate: {type(error).__name__}")
            return None
        if rate.model_extra:
            log.debug("portal_rate_extra_fields", extra={"fields": sorted(rate.model_extra)})
        try:
            return to_option(rate, self.now())
        except ValidationError:
            self._skip(airline, "rate failed contract checks")
            return None

    def _skip(self, airline: str, reason: str) -> None:
        self.last_errors.append(f"{airline}: {reason}")
        log.warning("portal_rate_skipped", extra={"airline": airline, "reason": reason})
