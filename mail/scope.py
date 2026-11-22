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


# Round 177 (declined by hand): "port-to-port sea freight shipment from Hamburg (DEHAM) to Jebel Ali
# (AEJEA) ... FCL shipment in 1 x 40ft container". The brief: "Air export RFQs only"; ocean freight is
# named out of scope. The extractor read it as air HAM to NUE (the signature town) and found no price.
SEA = re.compile(
    r"\b(?:sea ?freight|ocean ?freight|seefracht|seeweg|fret maritime|flete mar[ií]timo|trasporto marittimo|"
    r"fracht morski|zeevracht|FCL|LCL|full container load|less than container load|"
    r"\d+\s*x\s*(?:20|40|45)\s*(?:ft|foot|feet|')|(?:20|40|45)\s*(?:ft|foot|feet|')\s*(?:hc|high ?cube|container|dry))\b"
    r"|해상\s*운송|海运|船便|海上輸送",
    re.I,
)
AIR_WISH = re.compile(r"\b(?:air ?freight|by air|luftfracht|per luft|fret a[ée]rien|carga a[ée]rea|trasporto aereo|"
                      r"airway ?bill|AWB)\b|항공|空运|航空", re.I)


def sea_freight(subject: str, body: str) -> bool:
    """True for a sea/ocean freight request with no wish for air freight."""
    text = f"{'' if FORWARDED.match(subject or '') else subject or ''}\n{fresh_text(body) or body or ''}"
    return bool(SEA.search(text)) and not AIR_WISH.search(text)


def sea_decline_body(reference: str) -> str:
    return (
        "Hello,\n\n"
        "Thanks for thinking of us. I have to pass on this one, though: we only handle air freight exports out of "
        "Germany, so a sea freight shipment is outside what we can quote or book.\n\n"
        "A sea freight forwarder or the shipping line's own booking desk will be able to give you a proper "
        "all-in price for it.\n\n"
        "Whenever you have air shipments leaving Germany, we would be glad to quote them straight away. "
        f"Our reference is {reference}.\n\n"
        "Cheers,\nLena Hartmann\nWRATHOFCODE Air Freight"
    )
