from __future__ import annotations

import logging
import re
from decimal import Decimal

from core.agents.extractor import clean_body, find_currency
from core.contracts import RFQ, LlmUsage, Mail, Piece, Preference, RfqExtractor
from mail.extract import extract as rules_extract
from mail.text import fresh_text
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
    if x.tallest_cm:
        notes += (f"tallest_cm: {x.tallest_cm:g}",)
    if s.lithium_un3480:
        notes += ("UN3480",)
    if s.door_pickup and s.pickup_postcode:
        notes += (f"postcode: {s.pickup_postcode}",)
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
        pickup_postcode=s.pickup_postcode if s.door_pickup else None,
        currency=s.quote_currency or find_currency(clean_body(mail.body)),
        preference=Preference(x.preference),
        preference_assumed=not x.preference_stated,
        ready_date=s.ready_date,
        received_at=mail.received_at,
        notes=notes,
    )


SITE_UNKNOWN = "site_unknown"
GERMAN_AIRPORTS = re.compile(
    r"\b(FRA|MUC|DUS|HAM|STR|CGN|BER|HAJ|LEJ|NUE|BRE|DRS)\b|\b(frankfurt|munich|münchen|muenchen|düsseldorf|"
    r"duesseldorf|hamburg|stuttgart|cologne|köln|koeln|berlin|hannover|leipzig|nuremberg|nürnberg)\s+(airport|flughafen)\b",
    re.I,
)


def site_unknown(body: str, rfq: RFQ) -> bool:
    if not rfq.door_pickup:
        return False
    text = fresh_text(body or "")
    if re.search(r"\b\d{5}\b", text):
        return False
    if GERMAN_AIRPORTS.search(f"{rfq.subject}\n{text}"):
        return False
    return True


TOTAL_PIECES = re.compile(r"total\s+(?:pieces|pcs|packages|colli)\s*(?:\(\w+\))?\s*[:=|]\s*\|?\s*(\d{1,4})\b", re.I)
TOTAL_GROSS = re.compile(r"total\s+gross\s+weight\s*(?:\(kg\))?\s*[:=|]\s*\|?\s*(\d[\d.,]*)", re.I)
TOTAL_VOLUME = re.compile(r"total\s+volume\s*(?:\(cbm\)|\(m3\)|\(m³\))?\s*[:=|]\s*\|?\s*(\d[\d.,]*)", re.I)


def _number(text: str) -> Decimal | None:
    raw = text.strip().rstrip(".")
    if "," in raw and "." not in raw:
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(",", "")
    try:
        value = Decimal(raw)
    except Exception:
        return None
    return value if value > 0 else None


def document_totals(text: str) -> dict:
    """Totals a packing specification or SLI states ("Total volume (cbm): 1.92")."""
    found: dict = {}
    if m := TOTAL_PIECES.search(text):
        found["pieces"] = int(m.group(1))
    if (m := TOTAL_GROSS.search(text)) and (v := _number(m.group(1))):
        found["gross_kg"] = v
    if (m := TOTAL_VOLUME.search(text)) and (v := _number(m.group(1))):
        found["volume_cbm"] = v
    return found


class RulesFirstExtractor:
    def __init__(self, fallback: RfqExtractor, attachments=None) -> None:
        self.fallback = fallback
        self.attachments = attachments

    async def attachment_totals(self, mail: Mail, rfq: RFQ) -> RFQ:
        """The customer's packing document wins over the mail text.

        Round 33: the mail said 120 x 40 x 116 cm and 2.78 cbm, the attached packing
        specification said 1.92 cbm, and the customer confirmed the document was right.
        """
        try:
            texts = await self.attachments(mail)
        except Exception as error:
            log.warning("attachment_totals_failed", extra={"rfq": mail.id, "error": type(error).__name__})
            return rfq
        totals = document_totals("\n".join(t for _, t in texts if t))
        if "volume_cbm" not in totals and "gross_kg" not in totals:
            return rfq
        update: dict = {}
        if "gross_kg" in totals and totals["gross_kg"] != rfq.gross_kg:
            update["gross_kg"] = totals["gross_kg"]
        if "volume_cbm" in totals:
            update["volume_cbm"] = totals["volume_cbm"]
            update["pieces"] = ()  # the stated total volume replaces per-piece dimensions
        if "pieces" in totals:
            notes = tuple(n for n in rfq.notes if not n.startswith("pieces: "))
            update["notes"] = (*notes, f"pieces: {totals['pieces']}")
        if update:
            log.info("attachment_totals_used", extra={"rfq": mail.id, "totals": {k: str(v) for k, v in totals.items()}})
            rfq = rfq.model_copy(update=update)
        return rfq

    async def extract(self, mail: Mail) -> tuple[RFQ, LlmUsage | None]:
        try:
            body = clean_body(mail.body)
            x = rules_extract(mail.subject, body, mail.sender, str(mail.id))
            if (
                (x.shipment is None or not x.problems == [])
                and mail.attachments
                and self.attachments
            ):
                extra = "\n".join(t for _, t in await self.attachments(mail) if t)
                if extra:
                    y = rules_extract(mail.subject, f"{body}\n\n{extra}", mail.sender, str(mail.id))
                    if y.shipment is not None and (
                        x.shipment is None or len(y.problems) < len(x.problems)
                    ):
                        x = y
            if x.shipment is not None:
                rfq = to_rfq(mail, x)
                if mail.attachments and self.attachments:
                    rfq = await self.attachment_totals(mail, rfq)
                if site_unknown(body, rfq):
                    rfq = rfq.model_copy(update={"notes": (*rfq.notes, SITE_UNKNOWN)})
                log.info("rules_extract_ok", extra={"rfq": mail.id, "problems": x.problems})
                return rfq, None
            log.info("rules_extract_missing", extra={"rfq": mail.id, "missing": x.missing})
        except Exception as error:
            log.warning(
                "rules_extract_failed", extra={"rfq": mail.id, "error": type(error).__name__}
            )
        return await self.fallback.extract(mail)
