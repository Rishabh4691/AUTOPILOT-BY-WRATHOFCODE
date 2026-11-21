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
    r"\b(quote|quotation|rfq|request|anfrage|angebot|cotización|cotizacion|cotizar|devis|"
    r"cotation|preventivo|quotazione|wycen\w*|oferta|offerta|all-in price)\b",
    re.IGNORECASE,
)
ATTACHED_REQUEST = re.compile(
    r"\b(attach\w*|enclosed|recording|voice (?:message|memo|note)|video|anbei|anhang|angehängt|"
    r"beigefügt|sprachnachricht|ci-joint|pi[eè]ce jointe|adjunt\w*|allegat\w*|in allegato|za[lł][aą]cz\w*|"
    r"spreadsheet|document|pdf|file|scan|photo|picture|image)\b",
    re.IGNORECASE,
)
WEIGHT_PATTERN = re.compile(
    r"\d+[.,]?\d*\s*(kg|kgs|kilos?|kilograms?|kilogramm\w*|kilogrammes?|lb|lbs|pounds?|"
    r"t|tons?|tonnes?|tonnen)\b",
    re.IGNORECASE,
)
# Mails about an existing shipment or quote that arrive without reply headers.
NOT_A_REQUEST = re.compile(
    r"\b(we accept|accept (?:your|the) (?:offer|quot\w+)|quote accepted|"
    r"please (?:go ahead and )?book|tracking|where is (?:our|my) shipment|status (?:update|of)|"
    r"AWB\s*\d{3}[- ]?\d{8}|out of (?:the )?office|abwesen\w*|nicht im büro|automatic reply|"
    r"auto(?:matische)?[- ]?(?:reply|antwort)|invoice \d|payment confirmation|"
    r"thank(?:s| you) for (?:the|your) (?:quote|offer|quotation)|"
    r"danke für (?:das|ihr) angebot|vielen dank für (?:das|ihr) angebot)",
    re.IGNORECASE,
)
_PRICE = r"(?:me |us )?(?:a |an |your )?(?:quote|price|offer|rate)"
ASKS_FOR_PRICE = re.compile(
    rf"\b(please (?:quote|send {_PRICE}|provide (?:a )?(?:quote|price))|"
    rf"(?:could|can|would) you (?:please )?(?:quote|send {_PRICE}|give {_PRICE})|"
    r"quote request|request for (?:a )?quot\w+|need a (?:quote|price|rate)|"
    r"(?:bitte|benötigen|brauchen)[^.\n]{0,30}angebot|angebot für|anfrage luftfracht|devis|"
    r"cotiza\w+|preventivo|potete quotare|wycen\w*|all-in price|price for)\b",
    re.IGNORECASE,
)


def _text(mail: Mail) -> str:
    return f"{mail.subject}\n{mail.body}"


def looks_like_rfq(mail: Mail) -> bool:
    text = _text(mail)
    asks = bool(AIRPORT_PAIR_PATTERN.search(text) or REQUEST_WORD_PATTERN.search(text))
    if NOT_A_REQUEST.search(text) and not ASKS_FOR_PRICE.search(text):
        return False
    if asks and mail.attachments and ATTACHED_REQUEST.search(text):
        return True
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
