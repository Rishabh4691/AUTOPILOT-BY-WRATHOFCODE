from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from core.config import Settings, auth_headers
from core.contracts import RFQ, Mail, PriceOption

log = logging.getLogger("core.ratedesk")

LINE = re.compile(
    r"^\s*-\s*(?P<airline>[^()\n]+?)\s*\((?P<code>[A-Z0-9]{2})\)\s*:\s*(?P<total>\d[\d.,]*)\s*(?P<cur>[A-Z]{3})\s*,\s*"
    r"(?P<days>\d+)\s*days?\s*,\s*rate_id\s*(?P<rate>R-[A-Za-z0-9_-]+)\s*,\s*valid until\s*(?P<valid>[^\n]+)$",
    re.I | re.M,
)
REF = re.compile(r"\bref\s+(\d+)\b", re.I)
WAIT_S = 90.0
PORTAL_DOWN_TTL_S = 300.0


def parse_reply(body: str) -> list[dict]:
    out = []
    for m in LINE.finditer(body or ""):
        total = Decimal(m.group("total").replace(",", ""))
        try:
            valid = datetime.strptime(
                m.group("valid").strip().rstrip("."), "%d %b %Y %H:%M UTC"
            ).replace(tzinfo=UTC)
        except ValueError:
            valid = None
        out.append(
            {
                "airline": m.group("airline").strip(),
                "code": m.group("code"),
                "total": total,
                "currency": m.group("cur").upper(),
                "days": int(m.group("days")),
                "rate_id": m.group("rate"),
                "valid_until": valid,
            }
        )
    return out


class RateDeskSource:
    name = "ratedesk"

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        sender: Any,
        now: Callable[[], datetime],
    ) -> None:
        self.client = client
        self.settings = settings
        self.sender = sender
        self.now = now
        self._waiting: dict[int, asyncio.Future] = {}
        self._down_at = 0.0

    async def portal_down(self, rfq: RFQ) -> bool:
        if time.monotonic() - self._down_at < PORTAL_DOWN_TTL_S:
            return True
        try:
            r = await self.client.get(
                f"{self.settings.base_url}/v1/portal/rates",
                params={
                    "origin": rfq.origin,
                    "destination": rfq.destination,
                    "airline": "probe",
                    "weight_kg": "100",
                },
                headers=auth_headers(self.settings),
                timeout=8,
            )
        except httpx.HTTPError:
            return False
        if r.status_code == 503 and "unavailable" in r.text.lower():
            self._down_at = time.monotonic()
            return True
        return False

    def on_mail(self, mail: Mail) -> None:
        if mail.sender.strip().lower() != self.settings.rate_desk_address:
            return
        ref = REF.search(mail.body) or REF.search(mail.subject)
        if not ref:
            return
        future = self._waiting.get(int(ref.group(1)))
        if future is not None and not future.done():
            future.set_result(mail.body)

    async def quote(self, rfq: RFQ) -> list[PriceOption]:
        if not await self.portal_down(rfq):
            return []
        volume = rfq.volume_cbm
        if volume is None and rfq.pieces:
            from core.pricing.weight import volume_cbm

            volume = volume_cbm(rfq.pieces)
        subject = f"Rate request {rfq.origin}-{rfq.destination} ref {rfq.mail_id}"
        body = (
            f"Hello,\n\nplease send your rates for {rfq.origin}-{rfq.destination}, {rfq.gross_kg} kg"
            f"{f', {volume} cbm' if volume else ''}, all airlines.\n\nThanks\nWRATHOFCODE Air Freight"
        )
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._waiting[rfq.mail_id] = future
        try:
            await self.sender.send_new(self.settings.rate_desk_address, subject, body)
            log.info("ratedesk_requested", extra={"rfq": rfq.mail_id})
            reply = await asyncio.wait_for(future, timeout=WAIT_S)
        except TimeoutError:
            log.warning("ratedesk_timeout", extra={"rfq": rfq.mail_id})
            return []
        finally:
            self._waiting.pop(rfq.mail_id, None)
        options = []
        for row in parse_reply(reply):
            if row["currency"] != "EUR":
                continue
            options.append(
                PriceOption(
                    source="ratedesk",
                    carrier=row["airline"],
                    carrier_code=row["code"],
                    rate_id=row["rate_id"],
                    rate_id_at=self.now(),
                    valid_until=row["valid_until"],
                    total=row["total"],
                    currency="EUR",
                    transit_days=row["days"],
                )
            )
        log.info("ratedesk_options", extra={"rfq": rfq.mail_id, "options": len(options)})
        return options
