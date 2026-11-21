from __future__ import annotations

import logging
from decimal import Decimal

import httpx

from core.contracts import RFQ, LlmUsage, PriceOption
from core.pricing.weight import chargeable_kg
from mail import lang
from mail.extract import find_first_name
from mail.text import fresh_text
from mail.writer import write_quote_email

log = logging.getLogger("core.human_writer")

INCLUDES = {
    "freight": "freight",
    "fuel": "fuel",
    "security": "security",
    "pickup": "pickup",
    "fees": "handling",
}


class HumanEmailWriter:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def _original(self, rfq: RFQ) -> dict:
        try:
            r = await self.client.get(f"/v1/mailbox/messages/{rfq.mail_id}", timeout=5)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else {}
        except Exception as error:
            log.warning(
                "original_mail_unavailable",
                extra={"rfq": rfq.mail_id, "error": type(error).__name__},
            )
            return {}

    def _chargeable(self, rfq: RFQ, option: PriceOption) -> Decimal:
        if option.breakdown and option.breakdown.chargeable_kg:
            return option.breakdown.chargeable_kg
        try:
            return chargeable_kg(rfq.gross_kg, rfq.pieces, rfq.volume_cbm)
        except Exception:
            return rfq.gross_kg

    def _includes(self, option: PriceOption, door: bool) -> list[str]:
        b = option.breakdown
        if b is None:
            return ["freight", "fuel", "security"] + (["pickup"] if door else [])
        out = ["freight"]
        out += [k for k in ("fuel", "security") if getattr(b, k)]
        if b.fees or b.other_surcharges:
            out.append("handling")
        if door or b.pickup:
            out.append("pickup")
        return out

    async def write(
        self, rfq: RFQ, option: PriceOption, total: Decimal, currency: str
    ) -> tuple[str, LlmUsage | None]:
        original = await self._original(rfq)
        body = str(original.get("body") or "")
        sender = str(original.get("from") or rfq.customer)
        rfq_dict = {
            "id": str(rfq.mail_id),
            "reference": f"WOC-{rfq.mail_id}",
            "first_name": find_first_name(sender, body),
            "language": lang.detect(fresh_text(body) or rfq.subject),
            "origin": rfq.origin,
            "destination": rfq.destination,
            "pieces": sum(p.count for p in rfq.pieces) or 1,
            "gross_kg": float(rfq.gross_kg),
            "chargeable_kg": float(self._chargeable(rfq, option)),
            "preference": rfq.preference.value,
            "subject": rfq.subject,
            "customer_text": body,
        }
        price = {
            "total": float(total),
            "currency": currency,
            "carrier": option.carrier,
            "transit_days": option.transit_days,
            "valid_until": option.valid_until.isoformat() if option.valid_until else None,
            "includes": self._includes(option, rfq.door_pickup),
        }
        email = await write_quote_email(rfq_dict, price)
        usage = None
        if email.used_llm:
            usage = LlmUsage(
                model=str(email.tokens.get("model") or ""),
                input_tokens=int(email.tokens.get("in") or 0),
                output_tokens=int(email.tokens.get("out") or 0),
                cost_usd=Decimal(str(email.cost_usd)),
            )
        log.info(
            "human_writer",
            extra={"rfq": rfq.mail_id, "llm": email.used_llm, "fallback": email.fallback_reason},
        )
        return email.body, usage
