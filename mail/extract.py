import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sourcing.models import Piece, Shipment
from sourcing.weights import chargeable_weight_kg, gross_weight_kg, sanity_problems

from . import kit, lang
from .text import fresh_text
from .writer import preference

ORIGINS = {"FRA", "MUC", "DUS", "HAM", "STR", "CGN", "BER", "HAJ", "LEJ", "NUE", "BRE", "DRS", "FMO", "PAD", "SCN", "TXL"}
CITIES = {
    "frankfurt": "FRA", "munich": "MUC", "münchen": "MUC", "muenchen": "MUC", "munchen": "MUC", "düsseldorf": "DUS",
    "duesseldorf": "DUS", "dusseldorf": "DUS", "hamburg": "HAM", "stuttgart": "STR", "cologne": "CGN", "köln": "CGN",
    "koeln": "CGN", "berlin": "BER", "hannover": "HAJ", "hanover": "HAJ", "leipzig": "LEJ", "nuremberg": "NUE", "nürnberg": "NUE",
    "new york": "JFK", "chicago": "ORD", "los angeles": "LAX", "miami": "MIA", "dallas": "DFW", "atlanta": "ATL",
    "toronto": "YYZ", "mexico city": "MEX", "bogota": "BOG", "bogotá": "BOG", "lima": "LIM", "santiago": "SCL",
    "buenos aires": "EZE", "são paulo": "GRU", "sao paulo": "GRU", "dubai": "DXB", "doha": "DOH", "riyadh": "RUH",
    "tel aviv": "TLV", "cairo": "CAI", "nairobi": "NBO", "lagos": "LOS", "johannesburg": "JNB", "mumbai": "BOM",
    "delhi": "DEL", "new delhi": "DEL", "bangkok": "BKK", "singapore": "SIN", "kuala lumpur": "KUL", "ho chi minh": "SGN",
    "saigon": "SGN", "hong kong": "HKG", "shanghai": "PVG", "beijing": "PEK", "seoul": "ICN", "tokyo": "NRT",
    "taipei": "TPE", "manila": "MNL", "sydney": "SYD", "melbourne": "MEL", "kathmandu": "KTM", "ulaanbaatar": "ULN",
    "antananarivo": "TNR", "asuncion": "ASU", "asunción": "ASU", "papeete": "PPT",
}
NUM = r"\d+(?:[.,]\d+)?"
DIMS = re.compile(
    rf"(?:(?P<count>\d+)\s*(?:x|×|\*|pcs?\.?|pieces?|pallets?|cartons?|boxes|crates?|colli|kolli|colis|bultos|paletten?|palettes?|paczk\w*|szt\.?|ctns?|skids?|stk\.?|stück|st\.)\s*(?:of|à|a|de|di|zu je|je|@|:|,|-)?\s*)?"
    rf"(?P<l>{NUM})\s*(?:x|×|\*)\s*(?P<w>{NUM})\s*(?:x|×|\*)\s*(?P<h>{NUM})\s*(?P<unit>cm|mm|m|in|inch(?:es)?|\")?"
    rf"(?:[^\n\d]{{0,25}}?(?P<pre>\b(?:each|je|à|chacun|cada|uno|ciascuno|każd\w*)\s*)?(?P<pw>{NUM})\s*(?P<pwu>kgs?|lbs?|pounds?)\s*(?P<each>each|per piece|/\s*pc|je|chacun|cada|ciascuno|każd\w*)?)?",
    re.I,
)
WEIGHT = re.compile(rf"(?P<v>\d{{1,3}}(?:[ ,.]\d{{3}})+(?:[.,]\d+)?|{NUM})\s*(?P<u>kgs?|kilos?|kilograms?|lbs?|pounds?)\b", re.I)
TOTAL_HINT = re.compile(r"total|gross|gesamt|brutto|poids|peso|waga|łącz|totale|in total|insgesamt", re.I)
FAST = re.compile(r"\b(fastest|asap|urgent|express|quickest|as soon as possible|priority|schnellst\w*|eilig|dringend|so schnell|le plus rapide|urgente?|lo antes posible|más rápido|il più veloce|prima possibile|najszybc\w*|pilne)\b", re.I)
CHEAP = re.compile(r"\b(cheapest|lowest|möglichst günstig|so günstig wie möglich|best price|budget|economy|günstigst\w*|billigst\w*|preiswert\w*|le moins cher|moins cher|más barat\w*|económic\w*|più economic\w*|najtańsz\w*)\b", re.I)
PICKUP = re.compile(r"\b(pick ?up|collect(ion)? from|door|truck(ing)? (from|to the)|from our (site|warehouse|factory|premises)|abholung|abholen|ab werk|vorlauf|enlèvement|ramassage|camionnage|recogida|recoger|ritiro|odbiór|odebrać)\b", re.I)
POSTCODE = re.compile(r"\b(?:D-?)?(\d{5})\b")
VOLUME = re.compile(rf"(?P<v>{NUM})\s*(?:cbm|m3|m³|cubic met(?:re|er)s?|kubikmeter|mètres? cubes?|metros? cúbicos?|metri cubi)\b", re.I)
COUNT_ONLY = re.compile(
    r"\b(?P<n>\d{1,4})\s*(?:x\s*)?(?:pcs?\.?|pieces?|pallets?|cartons?|boxes|crates?|packages?|parcels?|colli|kolli|colis|bultos|paletten?|palettes?|stk\.?|stück|szt\.?|paczk\w*|ctns?|skids?|cases?)\b",
    re.I,
)
READY = re.compile(r"\b(?:ready|pickup|abholbereit|bereit|disponible|listo|pronto|gotow\w*)\D{0,40}?(\d{4})-(\d{2})-(\d{2})|\b(?:ready|bereit|abholbereit|disponible|listo|pronto|gotow\w*)\D{0,40}?(\d{1,2})\.(\d{1,2})\.(\d{4})", re.I)
LITHIUM = re.compile(r"UN\s?3480|lithium[- ]ion batter(y|ies) (packed )?alone", re.I)
SIGNOFF = re.compile(
    r"^(thanks?|thank you|cheers|best|best regards|kind regards|regards|many thanks|viele grüße|beste grüße|mit freundlichen grüßen|grüße|danke|gruß|"
    r"cordialement|merci|bien à vous|salutations|saludos|un saludo|gracias|atentamente|grazie|cordiali saluti|saluti|un saluto|pozdrawiam|dziękuję|z poważaniem)[\s,.!]*$",
    re.I,
)


@dataclass
class Extracted:
    shipment: Shipment | None
    first_name: str
    language: str
    preference: str
    preference_stated: bool = False
    missing: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    gross_kg: float | None = None
    chargeable_kg: float | None = None
    pieces: int = 0


def num(s: str) -> Decimal:
    s = s.strip().replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", s):
        return Decimal(re.sub(r"[.,]", "", s))
    return Decimal(s.replace(",", "."))


def airports():
    known = set(ORIGINS)
    for c in kit.carriers().values():
        if c.kind == "airline":
            known.update(c.serves)
    for z in kit.pickup_zones().values():
        known.add(z["airport"])
    return known


LABELS = {
    "o": r"(?:origin|from|von|ab|de|desde|da|z|departure|abflug|départ|partenza|salida)",
    "d": r"(?:destination|to|nach|à|vers|hacia|a|per|do|bis|ziel|destino|destinazione|arrivée)",
}


def find_route(text: str) -> tuple[str | None, str | None]:
    known = airports()
    labelled = {}
    for key, pat in LABELS.items():
        m = re.search(rf"\b{pat}\s*[:\-]?\s*(?:airport\s*)?\(?([A-Z]{{3}})\)?\b", text)
        if m and m.group(1) in known:
            labelled[key] = m.group(1)
    seq = [c for c in re.findall(r"\b[A-Z]{3}\b", text) if c in known]
    if len(set(seq)) < 2:
        low = text.lower()
        found = sorted((m.start(), code) for name, code in CITIES.items() for m in re.finditer(rf"\b{re.escape(name)}\b", low))
        seq += [code for _, code in found]
    origin = labelled.get("o") or next((c for c in seq if c in ORIGINS), None)
    dest = labelled.get("d") or next((c for c in seq if c != origin and c not in ORIGINS), None)
    dest = dest or next((c for c in seq if c != origin), None)
    return origin, dest


def find_pieces(text: str) -> list[Piece]:
    out = []
    for m in DIMS.finditer(text):
        unit = (m.group("unit") or "cm").lower()
        l, w, h = (num(m.group(k)) for k in ("l", "w", "h"))
        if unit == "mm":
            l, w, h, unit = l / 10, w / 10, h / 10, "cm"
        elif unit == "m":
            l, w, h, unit = l * 100, w * 100, h * 100, "cm"
        elif unit.startswith("in") or unit == '"':
            unit = "in"
        else:
            unit = "cm"
        count = int(m.group("count") or 1)
        weight = None
        wunit = "kg"
        if m.group("pw") and (m.group("each") or m.group("pre")):
            weight = num(m.group("pw"))
            wunit = "lb" if m.group("pwu").lower().startswith(("lb", "pound")) else "kg"
        out.append(Piece(count=count, length=l, width=w, height=h, dim_unit=unit, weight=weight, weight_unit=wunit))
    return out


def find_gross(text: str, pieces: list[Piece]) -> tuple[Decimal | None, str]:
    found = []
    for m in WEIGHT.finditer(text):
        unit = "lb" if m.group("u").lower().startswith(("lb", "pound")) else "kg"
        before = text[max(0, m.start() - 40) : m.start()]
        after = text[m.end() : m.end() + 15]
        each = re.search(r"each|per piece|/\s*pc|je\b|chacun|cada|ciascuno|każd", after + before[-12:], re.I)
        found.append((num(m.group("v")), unit, bool(TOTAL_HINT.search(before)), bool(each)))
    totals = [f for f in found if f[2] and not f[3]]
    if totals:
        return totals[-1][0], totals[-1][1]
    if pieces and all(p.weight is not None for p in pieces):
        return None, pieces[0].weight_unit
    plain = [f for f in found if not f[3]]
    if plain:
        best = max(plain, key=lambda f: f[0])
        return best[0], best[1]
    return None, "kg"


def sender_email(sender: str) -> str:
    s = (sender or "").strip().lower()
    return s[s.index("<") + 1 : s.index(">")] if "<" in s and ">" in s else s


def find_ready(text: str) -> date | None:
    m = READY.search(text)
    if not m:
        return None
    try:
        if m.group(1):
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
    except ValueError:
        return None


def find_first_name(sender: str, text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    for i, line in enumerate(lines):
        if SIGNOFF.match(line) and i + 1 < len(lines):
            cand = re.split(r"[\s,]", lines[i + 1])[0]
            if re.fullmatch(r"[A-ZÀ-ÝĄĆĘŁŃÓŚŹŻ][a-zà-ÿąćęłńóśźż'-]{1,20}", cand):
                return cand
    m = re.search(r"\b(?:regards|thanks|cheers|grüße|merci|saludos|saluti|pozdrawiam)[,.!]?\s+([A-Z][a-zà-ÿ'-]{1,20})\s*$", text or "", re.I | re.M)
    if m:
        return m.group(1)
    if "<" in (sender or ""):
        name = sender.split("<")[0].strip().strip('"')
        if name and "@" not in name:
            return name.split()[0].title()
    part = re.split(r"[._-]", sender_email(sender).split("@")[0])[0]
    generic = ("info", "sales", "export", "logistics", "shipping", "procurement", "buyer", "orders")
    return part.title() if part.isalpha() and len(part) > 1 and part not in generic else ""


def extract(subject: str, body: str, sender: str, rfq_id: str) -> Extracted:
    text = f"{subject}\n{fresh_text(body)}"
    language = lang.detect(fresh_text(body) or subject)
    stated = bool(FAST.search(text) or CHEAP.search(text))
    pref = "fastest" if FAST.search(text) and not CHEAP.search(text) else preference(None)
    origin, dest = find_route(text)
    pieces = find_pieces(text)
    gross, wunit = find_gross(text, pieces)
    door = bool(PICKUP.search(text))
    postcode = next((p for p in POSTCODE.findall(text)), None) if door else None
    zones = kit.pickup_zones()
    zone = postcode[:2] if postcode and postcode[:2] in zones else None
    if door and origin is None and zone:
        origin = zones[zone]["airport"]

    vol = VOLUME.search(text)
    volume = num(vol.group("v")) if vol and not pieces else None
    counted = sum(p.count for p in pieces) or sum(int(m.group("n")) for m in COUNT_ONLY.finditer(text))
    missing = [k for k, v in (("origin", origin), ("destination", dest)) if not v]
    if gross is None and not (pieces and all(p.weight is not None for p in pieces)):
        missing.append("gross weight")
    shipment = None
    problems = []
    gross_kg = charge = None
    if not missing:
        shipment = Shipment(
            rfq_id=rfq_id, origin=origin, destination=dest, pieces=pieces, gross_weight=gross, weight_unit=wunit,
            volume_cbm=volume,
            preference=pref, door_pickup=door, pickup_zone=zone, pickup_postcode=postcode,
            lithium_un3480=bool(LITHIUM.search(text)),
            ready_date=find_ready(text),
        )
        gross_kg = float(gross_weight_kg(shipment))
        charge = float(chargeable_weight_kg(shipment))
        problems = sanity_problems(shipment)
        if not pieces and volume is None:
            problems.append("no dimensions given, chargeable = gross")
        if door and not zone:
            problems.append("door pickup asked but no pickup zone found")
    return Extracted(
        shipment=shipment,
        first_name=find_first_name(sender, body),
        preference_stated=stated,
        language=language,
        preference=pref,
        missing=missing,
        problems=problems,
        gross_kg=gross_kg,
        chargeable_kg=charge,
        pieces=counted or (1 if gross else 0),
    )
