"""Booking when the customer says yes.

    result = await book_option(option, team_reference="RFQ-123", portal=portal,
                               shipment=shipment, carriers=carriers)
    if result.status == "email":   # send result.email with the mailbox client
    ...

Portal option:
  rate_id still valid (valid_until > now + 60 s)  -> book it
  else                                            -> fresh rate, same query, book
  410 expired / 404 unknown / 409 used elsewhere  -> fresh rate once, book again
  200                                             -> safe retry, already booked
  503                                             -> book by email with the airline
Sheet or bid option (no rate_id):
  airline is on the portal for this lane -> rate at the billed weight, book it
  otherwise                              -> booking email to the carrier
Then a mail "Booking BK-... confirmed" arrives: parse_booking_confirmation().
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from .bids import Carrier
from .models import PriceOption, Shipment
from .portal import (
    AlreadyBooked,
    NotOnPortal,
    PortalClient,
    PortalError,
    PortalUnavailable,
    RateExpired,
    UnknownRate,
)
from .weights import gross_weight_kg, total_volume_cbm

SAFETY_MARGIN = timedelta(seconds=60)


@dataclass
class BookingResult:
    status: Literal["booked", "email", "failed"]
    booking_reference: str | None = None
    rate_id: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    airline_code: str | None = None
    price_changed: bool = False  # fresh rate differs from what we quoted
    email: dict | None = None  # {'to','subject','body'} when status == 'email'
    notes: list[str] = field(default_factory=list)


def _fresh_enough(option: PriceOption, now: datetime) -> bool:
    return bool(option.rate_id and option.valid_until and option.valid_until > now + SAFETY_MARGIN)


async def _fresh_rate(portal: PortalClient, q: dict):
    return await portal.rate(q["origin"], q["destination"], q["airline"], q["weight_kg"], q.get("volume_cbm", 0))


async def _book_rate_id(portal, rate_id, team_reference, result: BookingResult) -> BookingResult:
    booking, created = await portal.book(rate_id, team_reference)
    result.status = "booked"
    result.booking_reference = booking.booking_reference
    result.rate_id = booking.rate_id
    result.price = booking.price
    result.currency = booking.currency
    result.airline_code = booking.airline_code
    result.notes.append("booked" if created else "already booked (safe retry)")
    return result


def booking_email(option: PriceOption, team_reference: str, to: str, s: Shipment | None) -> dict:
    lines = [
        f"Hello {option.airline or 'team'},",
        "",
        "please book this shipment at your offer:",
        "",
        f"Our reference: {team_reference}",
        f"Route: {option.origin} -> {option.destination}",
    ]
    if s is not None:
        lines.append(f"Gross weight: {gross_weight_kg(s):.1f} kg, volume {total_volume_cbm(s):.3f} m3")
    if option.billed_weight_kg is not None:
        lines.append(f"Chargeable weight: {option.billed_weight_kg} kg")
    lines += [
        f"Agreed price: {option.total} {option.currency} all-in",
        "",
        "Please confirm with your booking reference.",
        "",
        "Thank you,",
        "WRATHOFCODE",
    ]
    return {
        "to": to,
        "subject": f"[BOOK {team_reference}] Booking request {option.origin}-{option.destination}",
        "body": "\n".join(lines),
    }


def _carrier_email(option: PriceOption, carriers: list[Carrier] | None) -> str | None:
    if option.carrier_email:
        return option.carrier_email
    for c in carriers or []:
        if c.kind == "airline" and option.airline_code and c.airline_code == option.airline_code:
            return c.email
    return None


async def book_option(
    option: PriceOption,
    team_reference: str,
    portal: PortalClient,
    shipment: Shipment | None = None,
    carriers: list[Carrier] | None = None,
    now: datetime | None = None,
) -> BookingResult:
    now = now or datetime.now(UTC)
    result = BookingResult(status="failed", airline_code=option.airline_code)

    def by_email(reason: str) -> BookingResult:
        to = _carrier_email(option, carriers)
        result.notes.append(reason)
        if to is None:
            result.notes.append("no carrier email found: book by hand")
            return result
        result.status = "email"
        result.email = booking_email(option, team_reference, to, shipment)
        return result

    query = option.rate_query
    if query is None and (option.airline_code or option.airline):
        # sheet or bid option: is this airline bookable on the portal?
        # (sheets key airlines by name slug, the portal by 2-letter code)
        try:
            lane = await portal.lane(option.origin, option.destination)
        except PortalError:
            lane = None
        code, name = (option.airline_code or "").upper(), (option.airline or "").lower()
        match = next(
            (a for a in (lane.airlines if lane else []) if a.code.upper() == code or a.name.lower() == name),
            None,
        )
        if match:
            weight = option.billed_weight_kg or (gross_weight_kg(shipment) if shipment else None)
            if weight is not None:
                query = {
                    "origin": option.origin,
                    "destination": option.destination,
                    "airline": match.code,
                    "weight_kg": str(weight),
                    "volume_cbm": str(total_volume_cbm(shipment)) if shipment else "0",
                }
                result.notes.append("airline is on the portal: booking via a portal rate")
    if query is None:
        return by_email("no portal rate for this option")

    rate_id = option.rate_id if _fresh_enough(option, now) else None
    for attempt in (1, 2):
        try:
            if rate_id is None:
                rate = await _fresh_rate(portal, query)
                rate_id = rate.rate_id
                if rate.total != option.total or rate.currency != option.currency:
                    result.price_changed = True
                    result.notes.append(
                        f"fresh rate {rate.total} {rate.currency} vs quoted {option.total} {option.currency}"
                    )
            return await _book_rate_id(portal, rate_id, team_reference, result)
        except (RateExpired, UnknownRate, AlreadyBooked) as e:
            result.notes.append(f"{type(e).__name__}: {e}")
            rate_id = None  # try once more with a fresh rate
            if attempt == 2:
                return result
        except PortalUnavailable as e:
            return by_email(f"portal unavailable: {e}")
        except NotOnPortal as e:
            return by_email(f"not on portal: {e}")
        except PortalError as e:
            result.notes.append(f"{type(e).__name__}: {e}")
            return result
    return result


_CONFIRM = re.compile(r"Booking\s+(BK-[A-Za-z0-9]{8})\s+confirmed", re.I)


def parse_booking_confirmation(subject: str = "", body: str = "") -> str | None:
    """'Booking BK-1A2B3C4D confirmed' -> 'BK-1A2B3C4D'."""
    m = _CONFIRM.search(f"{subject}\n{body}")
    return m.group(1) if m else None
