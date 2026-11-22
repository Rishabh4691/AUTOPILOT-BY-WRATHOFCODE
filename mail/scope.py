"""Requests outside the brief's scope ("Air export RFQs only, with a door-to-port option").

Round 159 (accepted with a polite decline): "an airport-to-airport air import from Tokyo airport
(NRT), JP, to Hamburg airport (HAM), Germany". The extractor read it as HAM to NRT and started
pricing an export. An import INTO Germany is not ours to quote.

Many export mails say "our buyer ... is importing from us in Germany": the goods still leave
Germany, so those stay in scope. Only a route from a non-German airport to a German one counts.
"""

from __future__ import annotations

import re

from mail.extract import FORWARDED
from mail.text import fresh_text

GERMAN_CODES = {
    "FRA", "MUC", "DUS", "HAM", "STR", "CGN", "BER", "HAJ", "LEJ", "NUE", "BRE", "DRS", "DTM", "FMO",
    "PAD", "SCN", "FKB", "FDH", "HHN", "NRN", "TXL", "SXF",
}
GERMAN_CITIES = (
    r"frankfurt|munich|münchen|muenchen|düsseldorf|duesseldorf|hamburg|stuttgart|cologne|köln|koeln|"
    r"berlin|hannover|hanover|leipzig|nuremberg|nürnberg|nuernberg|bremen|dresden|dortmund"
)
NOT_AIRPORT = {"EUR", "USD", "CHF", "GBP", "CBM", "PDF", "KGS", "LBS", "PCS", "CTN", "PLT", "FCA", "DAP", "DDP",
               "EXW", "CPT", "CIP", "UTC", "CET", "SLI", "AWB", "ETA", "ETD", "DGR", "MSDS", "THE", "AND"}
# "from Tokyo airport (NRT), JP, to Hamburg airport (HAM)" / "NRT to HAM" / "from NRT to Hamburg"
# Every upper-case code is tried as the origin on its own: one regex sweep let "EUR" (or, with re.I,
# "Air") claim the text and hide the real "NRT".
CODE = re.compile(r"\b[A-Z]{3}\b")
TO_GERMANY = re.compile(
    r"\)?[^.\n]{0,80}?\bto\b[^.\n]{0,60}?"
    rf"(?:\(?\b(?P<dest>(?-i:{'|'.join(sorted(GERMAN_CODES))}))\b\)?|(?P<city>{GERMAN_CITIES})\b)",
    re.I,
)


def import_into_germany(subject: str, body: str) -> tuple[str, str] | None:
    """(origin, German destination) when the request flies INTO Germany, else None."""
    texts = [fresh_text(body) or body or ""]
    if subject and not FORWARDED.match(subject):
        texts.insert(0, subject)
    for text in texts:
        for code in CODE.finditer(text):
            origin = code.group(0)
            if origin in NOT_AIRPORT or origin in GERMAN_CODES:
                continue
            # The code must BE the origin: "from Tokyo airport (NRT)" (a "from" with no "to" between it
            # and the code) or a bare route "NRT to HAM". "to DXB ... we deliver it to MUC" is an
            # export and must not match (rounds 129, 138).
            before = text[max(0, code.start() - 70) : code.start()]
            from_part = re.search(r"\bfrom\b(?:(?!\bto\b)[^.\n?!])*$", before, re.I)
            m = TO_GERMANY.match(text, code.end())
            direct = m is not None and re.match(r"\)?\s*(?:to|-|–|→)\s", text[code.end() : code.end() + 6], re.I)
            if m and (from_part or direct):
                return origin, m.group("dest") or m.group("city").title()
    return None


def decline_body(origin: str, dest: str, reference: str) -> str:
    return (
        "Hello,\n\n"
        "Thanks for thinking of us. I have to pass on this one, though: we only handle air exports out "
        f"of Germany, so an import from {origin} into {dest} is outside what we can quote or book.\n\n"
        "A forwarder that handles imports into Germany, or your supplier's forwarder at origin, will be "
        "able to give you a proper all-in price for this shipment.\n\n"
        "Whenever you have shipments leaving Germany, we would be glad to quote them straight away. "
        f"Our reference is {reference}.\n\n"
        "Cheers,\nLena Hartmann\nWRATHOFCODE Air Freight"
    )
