from __future__ import annotations

import re

from core.agents.directory import CarrierDirectory
from core.config import Settings
from core.contracts import Classification, Mail, MailKind

BOOKING_PATTERN = re.compile(r"booking\s+BK-\S+\s+confirmed", re.IGNORECASE)
STATUS_UPDATE = re.compile(r"\bBK-[A-Za-z0-9]{6,12}\b[\s\S]*^\s*status\s*:", re.IGNORECASE | re.MULTILINE)
TARIFF_PATTERN = re.compile(r"\b(tariff|rate\s+sheet|valid\s+from)\b", re.IGNORECASE)
AIRPORT_PAIR_PATTERN = re.compile(r"\b[A-Z]{3}\b.*?\b[A-Z]{3}\b", re.DOTALL)
REQUEST_WORD_PATTERN = re.compile(
    r"\b(quote|quotation|rfq|request|anfrage|cotización|cotizacion|devis)\b", re.IGNORECASE
)
WEIGHT_PATTERN = re.compile(r"\d+[.,]?\d*\s*(kg|kgs|lb|lbs)\b", re.IGNORECASE)


def _text(mail: Mail) -> str:
    return f"{mail.subject}\n{mail.body}"


def looks_like_rfq(mail: Mail) -> bool:
    text = _text(mail)
    asks = bool(AIRPORT_PAIR_PATTERN.search(text) or REQUEST_WORD_PATTERN.search(text))
    return asks and bool(WEIGHT_PATTERN.search(text))


class RuleClassifier:
    def __init__(self, settings: Settings, directory: CarrierDirectory) -> None:
        self._settings = settings
        self._directory = directory

    def classify(self, mail: Mail, known_rfq_threads: frozenset[int]) -> Classification:
        by_sender = self._by_sender(mail)
        if by_sender is not None:
            return by_sender
        if (
            mail.thread_root_id in known_rfq_threads
            or mail.in_reply_to is not None
            or mail.references
        ):
            return Classification(kind=MailKind.FOLLOW_UP, reason="reply in an existing thread")
        if looks_like_rfq(mail):
            return Classification(
                kind=MailKind.RFQ, reason="mentions a route or quote and a weight"
            )
        return Classification(kind=MailKind.OTHER, reason="no rule matched")

    def _by_sender(self, mail: Mail) -> Classification | None:
        sender = mail.sender.strip().lower()
        if sender == self._settings.our_address:
            return Classification(kind=MailKind.OWN, reason="sent by us")
        if sender == self._settings.rate_desk_address:
            return Classification(kind=MailKind.PORTAL_REPLY, reason="from the rate desk")
        if sender == self._settings.tracking_address:
            return Classification(kind=MailKind.TRACKING, reason="from the tracking desk")
        contact = self._directory.by_email(sender)
        if contact is None:
            return None
        if contact.kind == "trucker":
            return Classification(kind=MailKind.TRUCKER_BID, reason=f"from trucker {contact.name}")
        return self._airline(mail, contact.name)

    def _airline(self, mail: Mail, name: str) -> Classification:
        text = _text(mail)
        if BOOKING_PATTERN.search(text):
            return Classification(
                kind=MailKind.BOOKING_CONFIRMATION, reason=f"booking confirmed by {name}"
            )
        if STATUS_UPDATE.search(text):
            return Classification(
                kind=MailKind.BOOKING_CONFIRMATION, reason=f"booking status update from {name}"
            )
        if TARIFF_PATTERN.search(text) or mail.attachments:
            return Classification(kind=MailKind.TARIFF, reason=f"tariff from {name}")
        return Classification(kind=MailKind.CARRIER_BID, reason=f"bid from airline {name}")
