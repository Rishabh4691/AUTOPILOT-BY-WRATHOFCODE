"""Spot requests that hold more than one shipment, and replies that accept only part of one.

Roadmap section 18 ("multiple parcels from multiple locations"): a mail with lot A at one site and
lot B at another, or one origin to two destinations, was read as a single shipment (one route,
summed or partial weight). How such a case is scored is not published yet, so this only *detects*
it: the extractor adds a "multi_lot: N" note so the case is visible and can be handled once the
rule is known. Rules only, no LLM call.
"""

from __future__ import annotations

import re

from .text import fresh_text

WEIGHT = re.compile(r"\b\d[\d.,]*\s*(?:kg|kgs|kilos?|lbs?)\b", re.I)
# "Lot 1", "Shipment B", "parcel A", "first batch", "Sendung 2", "envoi B", "lote 1"...
LABEL = re.compile(
    r"\b(?:(?:lot|shipment|batch|parcel|consignment|sendung|partie|envoi|lote|partita|partia|zending)\s+"
    r"(?:[A-H]|[1-9]|one|two|three)\b|"
    r"(?:first|second|third|1st|2nd|3rd)\s+(?:batch|lot|shipment|parcel|consignment))",
    re.I,
)
AIRPORT_ROUTE = re.compile(r"\b([A-Z]{3})\s*(?:to|->|→|–|-|nach|vers|a|para|do)\s*([A-Z]{3})\b")
TO_AIRPORT = re.compile(r"\bto\s+([A-Z]{3})\b")


NOT_PLACES = {"EUR", "USD", "CHF", "GBP", "CBM", "KGS", "AWB", "PCS", "DDP", "DAP", "EXW", "FCA", "CPT", "CIP", "DG", "UN", "ETA", "ETD", "RFQ"}
# A place (postcode or airport code) or a ready date of its own makes a lot a separate shipment.
PLACE = re.compile(r"\b(?:\d{5}|[A-Z]{3}|\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}-\d{2}-\d{2})\b")
SITE = re.compile(r"\b(?:at|from|in)\s+(?:our\s+)?([A-Z][a-zäöü]+)\s+(?:site|warehouse|plant|factory|office|depot)\b|"
                  r"\b(?:at|from)\s+our\s+(?:site|warehouse|plant|factory|depot)\s+(?:in\s+)?(?:\d{5}\s+)?([A-Z][a-zäöü]+)")


def _places(segment: str) -> frozenset[str]:
    codes = {p for p in PLACE.findall(segment) if p not in NOT_PLACES}
    codes |= {a or b for a, b in SITE.findall(segment)}
    return frozenset(codes)


def _labelled_lots(text: str) -> int:
    """Labelled lots count as separate shipments only when they sit at different places, go to
    different airports or are ready on different days. "Lot 1 / Lot 2" with one route is one consignment (real rounds 7-9)."""
    marks = list(LABEL.finditer(text))
    places: list[frozenset[str]] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        segment = text[m.end():end][:240]
        if WEIGHT.search(segment):
            here = _places(segment)
            if here:
                places.append(here)
    return len(set(places)) if len(set(places)) >= 2 else 1


def _routes(text: str) -> int:
    pairs = {(a, b) for a, b in AIRPORT_ROUTE.findall(text) if a != b}
    return len(pairs)


def _destinations_with_weights(text: str) -> int:
    """'3 pieces, 300 kg to ORD. 2 pieces, 150 kg to PVG.' : one weight per destination."""
    found = set()
    for sentence in re.split(r"(?<=[.;\n])\s*", text):
        dests = set(TO_AIRPORT.findall(sentence))
        if len(dests) == 1 and WEIGHT.search(sentence):
            found |= dests
    return len(found)


def lots(text: str) -> int:
    """How many separate shipments the request describes (1 for a normal request)."""
    text = fresh_text(text or "")  # only the new message, never the quoted history
    return max(1, _labelled_lots(text), _routes(text), _destinations_with_weights(text))


# A reply that agrees to only some of the lots ("book parcel A only, hold B") or excludes one.
PARTIAL = re.compile(
    r"\b(?:lot|shipment|batch|parcel|consignment|pallet|carton)s?\s+(?:[A-H1-9]|one|two)?\s*only\b|"
    r"\bonly\s+(?:the\s+)?(?:first|second|one|lot|shipment|batch|parcel|consignment)\b|"
    r"\b(?:first|second)\s+(?:batch|lot|shipment|parcel)\s+only\b|"
    r"\bbut\s+not\s+(?:the\s+)?(?:(?-i:[A-Z]{3})\b|other\s+(?:lot|shipment|batch|parcel|one)|second|first|lot|shipment|batch|parcel)|"
    r"\b(?:hold|cancel|skip|drop)\s+(?:the\s+)?(?:lot|shipment|batch|parcel|consignment)\s+(?:[A-H1-9]|two|one)\b",
    re.I,
)


def partial_acceptance(text: str) -> bool:
    return bool(PARTIAL.search(text or ""))
