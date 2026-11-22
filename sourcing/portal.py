"""Rate portal client for https://api.start-hack.5u.ai (see docs/PORTAL.md).

    async with PortalClient() as portal:          # key from FIVEU_API_KEY
        options, notes = await get_portal_options(shipment, portal)
        booking, created = await portal.book(options[0].rate_id, "RFQ-123")

What the spec says (GET /openapi.json):
- /v1/portal/ports      lanes + airlines on each lane. Not rate-limited.
- /v1/portal/brackets   weight breaks of one airline. Not rate-limited.
- /v1/portal/rates      ONE airline, priced "in that weight's bracket".
                        Rate-limited per team key, fixed 1-minute window.
- /v1/portal/bookings   book by rate_id (valid ~15 min, see valid_until).

Because the portal prices the weight you ask for in that weight's bracket,
it does NOT bump you to a cheaper higher break. get_portal_options() also
asks for the next break up and keeps the cheaper rate.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from pydantic import BaseModel, ValidationError

from . import fx
from .models import ChargeLine, PriceOption, Shipment
from .weights import PORTAL_KG_PER_CBM, D, gross_weight_kg, money, total_volume_cbm

BASE_URL = os.getenv("FIVEU_BASE_URL", "https://api.start-hack.5u.ai")


# ----------------------------------------------------------------- schemas
class PortalAirline(BaseModel):
    code: str
    name: str


class PortalLane(BaseModel):
    origin: str
    destination: str
    airlines: list[PortalAirline]


class PortalPorts(BaseModel):
    lanes: list[PortalLane]


class PortalBrackets(BaseModel):
    airline: str
    airline_code: str
    breaks_kg: list[int]


class PortalRate(BaseModel):
    rate_id: str
    airline: str
    airline_code: str
    origin: str
    destination: str
    weight_kg: Decimal
    chargeable_weight_kg: Decimal
    total: Decimal  # freight + fuel + security
    currency: str
    fx_eur_per_usd: Decimal | None = None  # EUR per 1 unit of `currency`
    transit_days: int
    valid_until: datetime
    dataset_version: str


class PortalBooking(BaseModel):
    booking_reference: str
    team_reference: str
    rate_id: str
    airline: str
    airline_code: str
    price: Decimal
    currency: str
    status: str


# ------------------------------------------------------------------ errors
class PortalError(Exception):
    def __init__(self, message: str, status: int | None = None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


class PortalUnavailable(PortalError):
    """503. The message says where to get the rate instead (e.g. the rate desk)."""


class NotOnPortal(PortalError):
    """404 for an airline or lane. The message gives the address to email."""


class RateExpired(PortalError):
    """410 at booking: fetch a fresh rate first."""


class UnknownRate(PortalError):
    """404 at booking: unknown rate_id or issued to another team."""


class AlreadyBooked(PortalError):
    """409: rate_id already booked under another team_reference."""


class RateLimited(PortalError):
    """429 that did not clear within our wait budget."""


class SchemaChanged(PortalError):
    """Response no longer matches the spec: the setup changed. Raise an alarm."""


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:500]
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("message") or body)[:500]
    return str(body)[:500]


def _num(value: Decimal) -> str:
    """Decimal as plain text (no exponent) for query params."""
    return format(D(value).normalize(), "f")


# ------------------------------------------------------------------ client
class PortalClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
        http: httpx.AsyncClient | None = None,
        max_concurrency: int = 4,
        max_retries: int = 3,
        max_wait_s: float = 20.0,
        ports_ttl_s: float = 60.0,
        brackets_ttl_s: float = 600.0,
    ):
        key = api_key or os.getenv("FIVEU_API_KEY") or os.getenv("TEAM_KEY")
        headers = {"X-API-Key": key} if key else {}
        self._http = http or httpx.AsyncClient(base_url=base_url, headers=headers, timeout=15.0)
        if http is not None and key:
            self._http.headers["X-API-Key"] = key
        self._sem = asyncio.Semaphore(max_concurrency)
        self.max_retries = max_retries
        self.max_wait_s = max_wait_s
        self.ports_ttl_s = ports_ttl_s
        self.brackets_ttl_s = brackets_ttl_s
        self._ports: tuple[float, list[PortalLane]] | None = None
        self._brackets: dict[str, tuple[float, list[int]]] = {}
        # live numbers for the UI / decision log
        self.rate_limit: int | None = None
        self.rate_remaining: int | None = None
        self.dataset_version: str | None = None
        self.events: list[str] = []  # e.g. dataset changes, to show as alarms

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # -------------------------------------------------------------- core
    async def _request(self, method: str, path: str, **kw) -> httpx.Response:
        attempt = 0
        while True:
            attempt += 1
            try:
                async with self._sem:
                    resp = await self._http.request(method, path, **kw)
            except httpx.TransportError as e:
                if attempt > self.max_retries:
                    raise PortalError(f"network error on {path}: {e}") from e
                await asyncio.sleep(min(0.5 * 2 ** (attempt - 1), 4))
                continue
            self._note_limits(resp)
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", "1") or 1)
                if attempt > self.max_retries or wait > self.max_wait_s:
                    raise RateLimited(
                        f"rate limit on {path}, retry after {wait:.0f}s", 429, _detail(resp)
                    )
                await asyncio.sleep(wait)
                continue
            return resp

    def _note_limits(self, resp: httpx.Response) -> None:
        if "X-RateLimit-Limit" in resp.headers:
            self.rate_limit = int(resp.headers["X-RateLimit-Limit"])
        if "X-RateLimit-Remaining" in resp.headers:
            self.rate_remaining = int(resp.headers["X-RateLimit-Remaining"])

    @staticmethod
    def _parse(model, resp: httpx.Response):
        try:
            return model.model_validate(resp.json())
        except (ValidationError, ValueError) as e:
            raise SchemaChanged(
                f"{resp.request.url.path} answer does not match the spec: {e}",
                resp.status_code,
                resp.text[:500],
            ) from e

    # ----------------------------------------------------------- lookups
    async def ports(self, fresh: bool = False) -> list[PortalLane]:
        now = time.monotonic()
        if not fresh and self._ports and now - self._ports[0] < self.ports_ttl_s:
            return self._ports[1]
        resp = await self._request("GET", "/v1/portal/ports")
        if resp.status_code == 503:
            raise PortalUnavailable(_detail(resp), 503)
        if resp.status_code != 200:
            raise PortalError(f"ports: HTTP {resp.status_code}: {_detail(resp)}", resp.status_code)
        lanes = self._parse(PortalPorts, resp).lanes
        self._ports = (now, lanes)
        return lanes

    async def lane(self, origin: str, destination: str) -> PortalLane | None:
        o, d = origin.upper(), destination.upper()
        for lane in await self.ports():
            if lane.origin.upper() == o and lane.destination.upper() == d:
                return lane
        return None

    async def brackets(self, airline: str) -> list[int]:
        key = airline.upper()
        now = time.monotonic()
        hit = self._brackets.get(key)
        if hit and now - hit[0] < self.brackets_ttl_s:
            return hit[1]
        resp = await self._request("GET", "/v1/portal/brackets", params={"airline": airline})
        if resp.status_code == 404:
            raise NotOnPortal(_detail(resp), 404)
        if resp.status_code == 503:
            raise PortalUnavailable(_detail(resp), 503)
        if resp.status_code != 200:
            raise PortalError(f"brackets: HTTP {resp.status_code}: {_detail(resp)}", resp.status_code)
        breaks = sorted(self._parse(PortalBrackets, resp).breaks_kg)
        self._brackets[key] = (now, breaks)
        return breaks

    async def rate(
        self,
        origin: str,
        destination: str,
        airline: str,
        weight_kg,
        volume_cbm=0,
    ) -> PortalRate:
        params = {
            "origin": origin.upper(),
            "destination": destination.upper(),
            "airline": airline,
            "weight_kg": _num(weight_kg),
            "volume_cbm": _num(volume_cbm),
        }
        resp = await self._request("GET", "/v1/portal/rates", params=params)
        if resp.status_code == 404:
            raise NotOnPortal(_detail(resp), 404)
        if resp.status_code == 503:
            raise PortalUnavailable(_detail(resp), 503)
        if resp.status_code != 200:
            raise PortalError(f"rates: HTTP {resp.status_code}: {_detail(resp)}", resp.status_code)
        rate = self._parse(PortalRate, resp)
        if self.dataset_version and rate.dataset_version != self.dataset_version:
            self.events.append(
                f"{datetime.now(timezone.utc):%H:%M:%S} portal dataset changed "
                f"{self.dataset_version} -> {rate.dataset_version}"
            )
        self.dataset_version = rate.dataset_version
        if rate.fx_eur_per_usd is not None:
            fx.set_rate(rate.currency, rate.fx_eur_per_usd)
        # Rounds 93-97: keep every portal price, so a portal outage can still be priced.
        from sourcing import portal_cache

        hit = self._brackets.get(airline.upper())
        portal_cache.record(rate.origin, rate.destination, rate.airline, rate.airline_code,
                            rate.chargeable_weight_kg, rate.total, rate.currency, rate.transit_days,
                            breaks=[Decimal(b) for b in hit[1]] if hit else ())
        return rate

    # ------------------------------------------------------------ booking
    async def book(self, rate_id: str, team_reference: str) -> tuple[PortalBooking, bool]:
        """Returns (booking, created). created=False means a safe retry of an old booking."""
        resp = await self._request(
            "POST",
            "/v1/portal/bookings",
            json={"rate_id": rate_id, "team_reference": team_reference},
        )
        code = resp.status_code
        if code in (200, 201):
            return self._parse(PortalBooking, resp), code == 201
        msg = _detail(resp)
        if code == 404:
            raise UnknownRate(msg, 404)
        if code == 409:
            raise AlreadyBooked(msg, 409)
        if code == 410:
            raise RateExpired(msg, 410)
        if code == 503:
            raise PortalUnavailable(msg, 503)
        raise PortalError(f"booking: HTTP {code}: {msg}", code)


# ------------------------------------------------------------- price source
def _option_from_rate(rate: PortalRate, gross: Decimal, cbm: Decimal, note: str | None) -> PriceOption:
    total_eur = (
        money(rate.total)
        if rate.currency.upper() == "EUR"
        else (money(rate.total * rate.fx_eur_per_usd) if rate.fx_eur_per_usd else fx.to_eur(rate.total, rate.currency))
    )
    return PriceOption(
        source="portal",
        airline_code=rate.airline_code,
        airline=rate.airline,
        origin=rate.origin,
        destination=rate.destination,
        chargeable_weight_kg=rate.chargeable_weight_kg,
        billed_weight_kg=rate.chargeable_weight_kg,
        total=money(rate.total),
        currency=rate.currency,
        total_eur=total_eur,
        transit_days=rate.transit_days,
        lines=[
            ChargeLine(
                code="PORTAL",
                name="Air freight incl. fuel and security (portal)",
                basis="all_in",
                quantity=rate.chargeable_weight_kg,
                amount=money(rate.total),
            )
        ],
        rate_id=rate.rate_id,
        rate_query={
            "origin": rate.origin,
            "destination": rate.destination,
            "airline": rate.airline_code,
            "weight_kg": _num(rate.weight_kg),
            "volume_cbm": _num(cbm),
        },
        valid_until=rate.valid_until,
        dataset_version=rate.dataset_version,
        fetched_at=datetime.now(timezone.utc),
        notes=[note] if note else [],
    )


async def get_portal_options(
    rfq,
    portal: PortalClient,
    probe_next_break: bool = True,
) -> tuple[list[PriceOption], list[str]]:
    """One option per airline on the lane (cheapest of: own weight, next break up)."""
    from sourcing import portal_warm

    portal_warm.mark_live()  # the background cache warm-up steps aside for live quotes
    s = rfq if isinstance(rfq, Shipment) else Shipment.model_validate(rfq)
    notes: list[str] = []
    events_before = len(portal.events)
    try:
        lane = await portal.lane(s.origin, s.destination)
    except PortalError as e:
        return [], [f"portal ports failed: {type(e).__name__}: {e}"]
    if lane is None:
        return [], [f"portal has no lane {s.origin}-{s.destination}: price by email to the airline"]

    gross = gross_weight_kg(s)
    cbm = total_volume_cbm(s)
    portal_cw = max(gross, cbm * PORTAL_KG_PER_CBM)

    async def one(airline) -> PriceOption | None:
        weights: list[Decimal] = [gross]
        if probe_next_break:
            try:
                breaks = await portal.brackets(airline.code)
                nxt = next((D(b) for b in breaks if D(b) > portal_cw), None)
                if nxt is not None:
                    weights.append(nxt)
            except PortalError as e:
                notes.append(f"{airline.code} brackets: {e}")
        best: tuple[Decimal, PortalRate] | None = None
        for w in weights:
            try:
                r = await portal.rate(s.origin, s.destination, airline.code, w, cbm)
            except PortalError as e:
                notes.append(f"{airline.code} rate at {w} kg: {type(e).__name__}: {e}")
                continue
            if best is None or r.total < best[1].total:
                best = (w, r)
        if best is None:
            return None
        w, r = best
        note = (
            f"asked portal for {w} kg (next break): cheaper than {gross} kg"
            if w != gross
            else None
        )
        return _option_from_rate(r, gross, cbm, note)

    results = await asyncio.gather(*(one(a) for a in lane.airlines))
    options = [o for o in results if o is not None]
    options.sort(key=lambda o: (o.total_eur is None, o.total_eur or o.total))
    notes.extend(portal.events[events_before:])
    return options, notes
