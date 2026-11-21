from __future__ import annotations

import logging
from decimal import Decimal

from core.agents.extractor import clean_body
from core.contracts import RFQ, LlmUsage, Mail, Piece, Preference, RfqExtractor
from mail.extract import extract as rules_extract
from sourcing.weights import gross_weight_kg, to_cm, to_kg

log = logging.getLogger("core.rules_extractor")

ASSUMED = "No preference stated, quoted the cheapest routing."


def to_rfq(mail: Mail, x) -> RFQ:
    s = x.shipment
    pieces = []
    for p in s.pieces:
        weight = to_kg(p.weight, p.weight_unit) if p.weight is not None else None
        pieces.append(
            Piece(
                count=p.count,
                length_cm=to_cm(p.length, p.dim_unit),
                width_cm=to_cm(p.width, p.dim_unit),
                height_cm=to_cm(p.height, p.dim_unit),
                weight_kg=weight,
            )
        )
    notes = tuple(x.problems) + (() if x.preference_stated else (ASSUMED,))
    if not pieces and x.pieces:
        notes += (f"pieces: {x.pieces}",)
    return RFQ(
        mail_id=mail.id,
        thread_root_id=mail.thread_root_id,
        customer=mail.sender,
        subject=mail.subject,
        origin=s.origin,
        destination=s.destination,
        pieces=tuple(pieces),
        gross_kg=Decimal(gross_weight_kg(s)),
        volume_cbm=s.volume_cbm,
        door_pickup=s.door_pickup,
        pickup_zone=s.pickup_zone if s.door_pickup else None,
        preference=Preference(x.preference),
        preference_assumed=not x.preference_stated,
        ready_date=s.ready_date,
        received_at=mail.received_at,
        notes=notes,
    )


class RulesFirstExtractor:
    def __init__(self, fallback: RfqExtractor) -> None:
        self.fallback = fallback

    async def extract(self, mail: Mail) -> tuple[RFQ, LlmUsage | None]:
        try:
            x = rules_extract(mail.subject, clean_body(mail.body), mail.sender, str(mail.id))
            if x.shipment is not None:
                rfq = to_rfq(mail, x)
                log.info("rules_extract_ok", extra={"rfq": mail.id, "problems": x.problems})
                return rfq, None
            log.info("rules_extract_missing", extra={"rfq": mail.id, "missing": x.missing})
        except Exception as error:
            log.warning(
                "rules_extract_failed", extra={"rfq": mail.id, "error": type(error).__name__}
            )
        return await self.fallback.extract(mail)
