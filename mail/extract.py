import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sourcing.models import Piece, Shipment
from sourcing.weights import chargeable_weight_kg, gross_weight_kg, sanity_problems

from . import kit, lang
from .text import fresh_text
from .writer import preference

ORIGINS = {
    "FRA",
    "MUC",
    "DUS",
    "HAM",
    "STR",
    "CGN",
    "BER",
    "HAJ",
    "LEJ",
    "NUE",
    "BRE",
    "DRS",
    "FMO",
    "PAD",
    "SCN",
    "TXL",
}
CITIES = {
    "frankfurt": "FRA",
    "munich": "MUC",
    "münchen": "MUC",
    "muenchen": "MUC",
    "munchen": "MUC",
    "düsseldorf": "DUS",
    "duesseldorf": "DUS",
    "dusseldorf": "DUS",
    "hamburg": "HAM",
    "stuttgart": "STR",
    "cologne": "CGN",
    "köln": "CGN",
    "koeln": "CGN",
    "berlin": "BER",
    "hannover": "HAJ",
    "hanover": "HAJ",
    "leipzig": "LEJ",
    "nuremberg": "NUE",
    "nürnberg": "NUE",
    "new york": "JFK",
    "chicago": "ORD",
    "los angeles": "LAX",
    "miami": "MIA",
    "dallas": "DFW",
    "atlanta": "ATL",
    "toronto": "YYZ",
    "mexico city": "MEX",
    "bogota": "BOG",
    "bogotá": "BOG",
    "lima": "LIM",
    "santiago": "SCL",
    "buenos aires": "EZE",
    "são paulo": "GRU",
    "sao paulo": "GRU",
    "dubai": "DXB",
    "doha": "DOH",
    "riyadh": "RUH",
    "tel aviv": "TLV",
    "cairo": "CAI",
    "nairobi": "NBO",
    "lagos": "LOS",
    "johannesburg": "JNB",
    "mumbai": "BOM",
    "delhi": "DEL",
    "new delhi": "DEL",
    "bangkok": "BKK",
    "singapore": "SIN",
    "kuala lumpur": "KUL",
    "ho chi minh": "SGN",
    "saigon": "SGN",
    "hong kong": "HKG",
    "shanghai": "PVG",
    "beijing": "PEK",
    "seoul": "ICN",
    "tokyo": "NRT",
    "taipei": "TPE",
    "manila": "MNL",
    "sydney": "SYD",
    "melbourne": "MEL",
    "kathmandu": "KTM",
    "ulaanbaatar": "ULN",
    "antananarivo": "TNR",
    "asuncion": "ASU",
    "asunción": "ASU",
    "papeete": "PPT",
}
NUM = r"\d+(?:[.,]\d+)?"
DIMS = re.compile(
    rf"(?:(?P<count>\d+)\s*(?:x|×|\*|pcs?\.?|pieces?|pallets?|cartons?|boxes|crates?|colli|kolli|colis|bultos|paletten?|palettes?|paczk\w*|szt\.?|ctns?|skids?|stk\.?|stück|st\.)\s*(?:of|à|a|de|di|zu je|je|@|:|,|-)?\s*)?"
    rf"(?P<l>{NUM})\s*(?:x|×|\*|by)\s*(?P<w>{NUM})\s*(?:x|×|\*|by)\s*(?P<h>{NUM})\s*(?P<unit>cm|mm|m|in|inch(?:es)?|\")?"
    rf"(?:[^\n\d]{{0,25}}?(?P<pre>\b(?:each|je|à|chacun|cada|uno|ciascuno|każd\w*)\s*)?(?P<pw>{NUM})\s*(?P<pwu>kgs?|lbs?|pounds?)\s*(?P<each>each|per piece|/\s*pc|je|chacun|cada|ciascuno|każd\w*)?)?",
    re.I,
)
WEIGHT = re.compile(
    rf"(?P<v>\d{{1,3}}(?:[ ,.]\d{{3}})+(?:[.,]\d+)?|{NUM})\s*(?P<u>kgs?|kilos?|kilograms?|lbs?|pounds?|t|tons?|tonnes?|tonnen)\b",
    re.I,
)
NET_NEAR = re.compile(r"\b(net|netto|neto|nett|poids net|peso neto|peso netto)\b", re.I)
GROSS_NEAR = re.compile(
    r"\b(gross|brutto|bruto|lordo|brut|gesamtgewicht|total weight|poids brut|peso bruto)\b", re.I
)


def weight_kg(value: Decimal, unit: str) -> tuple[Decimal, str]:
    u = unit.lower()
    if u.startswith(("lb", "pound")):
        return value, "lb"
    if u in ("t", "ton", "tons", "tonne", "tonnes", "tonnen"):
        return value * 1000, "kg"
    return value, "kg"


TOTAL_HINT = re.compile(
    r"total|gross|gesamt|brutto|poids|peso|waga|łącz|totale|in total|insgesamt", re.I
)
FAST = re.compile(
    r"\b(fastest|asap|urgent|express|quickest|as soon as possible|priority|schnellst\w*|eilig|dringend|so schnell|le plus rapide|urgente?|lo antes posible|más rápido|il più veloce|prima possibile|najszybc\w*|pilne)\b",
    re.I,
)
CHEAP = re.compile(
    r"\b(cheapest|lowest|möglichst günstig|so günstig wie möglich|best price|budget|economy|günstigst\w*|billigst\w*|preiswert\w*|le moins cher|moins cher|más barat\w*|económic\w*|più economic\w*|najtańsz\w*)\b",
    re.I,
)
PICKUP = re.compile(
    r"\b(pick ?up|collect(ion)? from|door|truck(ing)? (from|to the)|from our (site|warehouse|factory|premises)|abholung|abholen|ab werk|vorlauf|enlèvement|ramassage|camionnage|recogida|recoger|ritiro|odbiór|odebrać)\b",
    re.I,
)
POSTCODE = re.compile(r"\b(?:D-?)?(\d{5})\b")
SELF_DELIVERY = re.compile(
    r"\b(?:we(?:'ll| will| shall)? (?:deliver|bring|drop)|deliver(?:ed)? (?:it|them|the (?:cargo|goods|shipment)) "
    r"(?:to|at) [^.]{0,40}(?:airport|terminal)[^.]{0,15}ourselves|ourselves to the (?:airport|terminal)|"
    r"selbst (?:an)?liefern|liefern (?:wir )?(?:es |die ware )?selbst|anlieferung durch uns)",
    re.I,
)
LOT = re.compile(r"\b(?:lot|position|pos\.|item|partie|teil(?:sendung)?)\s*\d+\s*[:)\-]", re.I)
VOLUME = re.compile(
    rf"(?P<v>{NUM})\s*(?P<u>cbm|m3|m³|cubic met(?:re|er)s?|kubikmeter|mètres? cubes?|metros? cúbicos?|metri cubi|cu\.?\s?ft|cubic f(?:ee|oo)t|ft3|ft³|cft)(?![a-z])",
    re.I,
)
CUFT = Decimal("0.0283168")


def volume_cbm_of(m) -> Decimal:
    u = (m.group("u") or "").lower().replace(" ", "")
    v = num(m.group("v"))
    return v * CUFT if u.startswith(("cu", "cubicf", "ft", "cft")) else v


COUNT_ONLY = re.compile(
    r"\b(?P<n>\d{1,4})\s*(?:x\s*)?(?:pcs?\.?|pieces?|pallets?|cartons?|boxes|crates?|packages?|parcels?|colli|kolli|colis|bultos|paletten?|palettes?|stk\.?|stück|szt\.?|paczk\w*|ctns?|skids?|cases?)\b",
    re.I,
)
READY = re.compile(
    r"\b(?:ready|pickup|abholbereit|bereit|disponible|listo|pronto|gotow\w*)\D{0,40}?(\d{4})-(\d{2})-(\d{2})|\b(?:ready|bereit|abholbereit|disponible|listo|pronto|gotow\w*)\D{0,40}?(\d{1,2})\.(\d{1,2})\.(\d{4})",
    re.I,
)
CURRENCY = re.compile(
    r"\b(?:in|price in|quote in|prices? in|all-in (?:price )?in|currency:?|währung:?|en|devise:?)\s*(USD|EUR|GBP|CHF|PLN|US ?dollars?|euros?|dollars?)\b",
    re.I,
)
UNIT_FIRST_WEIGHT = re.compile(
    rf"(?:gross )?weight\s*\((?P<u>kg|kgs|lbs?)\)\s*[:=]?\s*(?P<v>{NUM})", re.I
)
UNIT_FIRST_VOLUME = re.compile(rf"volume\s*\((?:cbm|m3|m³)\)\s*[:=]?\s*(?P<v>{NUM})", re.I)
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
    tallest_cm: float | None = None


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
        found = sorted(
            (m.start(), code)
            for name, code in CITIES.items()
            for m in re.finditer(rf"\b{re.escape(name)}\b", low)
        )
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
        out.append(
            Piece(
                count=count,
                length=l,
                width=w,
                height=h,
                dim_unit=unit,
                weight=weight,
                weight_unit=wunit,
            )
        )
    return out


LOT_LINE = re.compile(
    r"^\s*(?:lot|position|pos\.?|item|partie|teil(?:sendung)?|line)\s*\d+\s*[:)\-.]\s*(?P<rest>.+)$",
    re.I | re.M,
)
BULLET_LINE = re.compile(r"^\s*[-*•]\s*(?P<rest>\d.+)$", re.M)
EACH = r"(?:each|per (?:piece|unit|carton|case|drum|pallet|box)|je|chacun\w*|cada|ciascun\w*|każd\w*|pro stück)"
TOGETHER = r"(?:together|total|in total|combined|insgesamt|zusammen|gesamt|au total|en total|in totale|łącznie)"
LOT_COUNT = re.compile(r"^\D{0,12}?(\d{1,4})\s*(?:x\s*)?[a-zäöüéèàçñ]+", re.I)
LOT_WEIGHT = re.compile(
    rf"(?:(?P<pre>{EACH}|{TOGETHER})\s*)?(?P<v>{NUM})\s*(?P<u>kgs?|kilos?|lbs?|pounds?|t|tons?|tonnes?|tonnen)\b(?P<post>[^,;()\n]{{0,25}})",
    re.I,
)
LOT_VOLUME = re.compile(
    rf"(?:(?P<pre>{EACH}|{TOGETHER})\s*)?(?P<v>{NUM})\s*(?P<u>cbm|m3|m³|cubic met(?:re|er)s?|cu\.?\s?ft|cubic f(?:ee|oo)t|ft3|cft)(?![a-z])",
    re.I,
)
LOT_DIMS = re.compile(
    rf"(?:(?P<pre>{EACH})\s*)?(?P<l>{NUM})\s*(?:[x×*]|by)\s*(?P<w>{NUM})\s*(?:[x×*]|by)\s*(?P<h>{NUM})\s*(?P<u>cm|mm|m|in|inch(?:es)?)?",
    re.I,
)


def _to_kg(v: Decimal, unit: str) -> Decimal:
    value, u = weight_kg(v, unit)
    return value * Decimal("0.45359237") if u == "lb" else value


def _dims_cbm(m) -> Decimal:
    unit = (m.group("u") or "cm").lower()
    f = {
        "mm": Decimal("0.1"),
        "m": Decimal("100"),
        "in": Decimal("2.54"),
        "inch": Decimal("2.54"),
        "inches": Decimal("2.54"),
    }.get(unit, Decimal("1"))
    return (
        num(m.group("l")) * f * num(m.group("w")) * f * num(m.group("h")) * f / Decimal("1000000")
    )


MAX_HEIGHT: dict[str, Decimal] = {}


def tallest_cm(text: str) -> Decimal | None:
    best = None
    for m in LOT_DIMS.finditer(text):
        unit = (m.group("u") or "cm").lower()
        f = {"mm": Decimal("0.1"), "m": Decimal("100"), "in": Decimal("2.54"), "inch": Decimal("2.54"), "inches": Decimal("2.54")}.get(unit, Decimal("1"))
        h = num(m.group("h")) * f
        best = h if best is None or h > best else best
    for m in re.finditer(rf"height\s*(?:\(cm\))?\s*[:=]?\s*(?P<v>{NUM})\s*(?:cm)?", text, re.I):
        h = num(m.group("v"))
        best = h if best is None or h > best else best
    return best


def parse_lots(text: str) -> tuple[int, Decimal, Decimal] | None:
    lines = [m.group("rest") for m in LOT_LINE.finditer(text)] or [
        m.group("rest") for m in BULLET_LINE.finditer(text)
    ]
    if len(lines) < 2:
        return None
    pieces, gross, cbm = 0, Decimal(0), Decimal(0)
    for line in lines:
        c = LOT_COUNT.search(line)
        count = int(c.group(1)) if c else 1
        before_dims = LOT_DIMS.search(line)
        if c and before_dims and before_dims.start() <= c.start(1):
            count = 1
        weights = [
            w
            for w in LOT_WEIGHT.finditer(line)
            if not NET_NEAR.search(w.group("post")[:8] or "")
            and not NET_NEAR.search(line[max(0, w.start() - 10) : w.start()])
            and not re.search(r"\(\s*$", line[: w.start()])
        ]
        gross_hits = [
            w
            for w in weights
            if GROSS_NEAR.search(w.group("post") or "")
            or GROSS_NEAR.search(line[max(0, w.start() - 12) : w.start()])
        ] or weights
        if gross_hits:
            w = gross_hits[0]
            kg = _to_kg(num(w.group("v")), w.group("u"))
            each = bool(
                w.group("pre") and re.fullmatch(EACH, w.group("pre").strip(), re.I)
            ) or bool(re.match(rf"\s*{EACH}", w.group("post") or "", re.I))
            gross += kg * count if each else kg
        d = LOT_DIMS.search(line)
        v = LOT_VOLUME.search(line)
        if d:
            together = bool(re.search(rf"{TOGETHER}\s*$", line[: d.start()], re.I))
            cbm += _dims_cbm(d) * (1 if together else count)
        elif v:
            each = bool(v.group("pre") and re.fullmatch(EACH, v.group("pre").strip(), re.I))
            cbm += volume_cbm_of(v) * (count if each else 1)
        pieces += count
    return pieces, gross, cbm.quantize(Decimal("0.001"))


def find_currency(text: str) -> str | None:
    m = CURRENCY.search(text)
    if not m:
        return None
    v = m.group(1).upper().replace(" ", "")
    return (
        "USD"
        if "DOLLAR" in v or v in ("USD", "USDOLLAR", "USDOLLARS")
        else "EUR"
        if "EURO" in v
        else v[:3]
    )


def find_gross(text: str, pieces: list[Piece]) -> tuple[Decimal | None, str]:
    total_line = [
        m
        for m in UNIT_FIRST_WEIGHT.finditer(text)
        if re.search(r"total", text[max(0, m.start() - 12) : m.start()], re.I)
    ]
    if total_line:
        m = total_line[-1]
        return num(m.group("v")), "lb" if m.group("u").lower().startswith("lb") else "kg"
    found = []
    for m in WEIGHT.finditer(text):
        value, unit = weight_kg(num(m.group("v")), m.group("u"))
        before = text[max(0, m.start() - 40) : m.start()]
        after = text[m.end() : m.end() + 15]
        if NET_NEAR.search(before[-14:]) or NET_NEAR.search(after[:8]):
            continue
        each = re.search(
            r"each|per piece|/\s*pc|je\b|chacun|cada|ciascuno|każd", after + before[-12:], re.I
        )
        gross = bool(GROSS_NEAR.search(before[-22:]) or GROSS_NEAR.search(after[:10]))
        found.append((value, unit, bool(TOTAL_HINT.search(before)) or gross, bool(each), gross))
    explicit = [f for f in found if f[4] and not f[3]]
    if len(explicit) == 1:
        return explicit[0][0], explicit[0][1]
    totals = [f for f in found if f[2] and not f[3]]
    if len(totals) > 1 and len(LOT.findall(text)) > 1 and len({f[1] for f in totals}) == 1:
        return sum((f[0] for f in totals), Decimal(0)), totals[0][1]
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


NAME = re.compile(r"[A-ZÀ-ÝĄĆĘŁŃÓŚŹŻ][a-zà-ÿąćęłńóśźż'-]{1,20}")
NOT_A_NAME = re.compile(
    r"\b(gmbh|ag|ltd|llc|inc|bv|sa|srl|spa|sas|sp\. z|co|kg|team|logistics|logistik|freight|cargo|export|"
    r"purchasing|procurement|manager|head|director|department|abteilung|einkauf|medtech|group|company|"
    r"hi|hello|hey|dear|hallo|bonjour|hola|ciao|buongiorno|thanks|danke|merci|gracias|grazie)\b",
    re.I,
)


def _person(line: str) -> str:
    words = line.replace(",", " ").split()
    if (
        1 <= len(words) <= 3
        and all(NAME.fullmatch(w) for w in words)
        and not NOT_A_NAME.search(line)
    ):
        return words[0]
    return ""


def find_first_name(sender: str, text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    for i, line in enumerate(lines):
        if SIGNOFF.match(line) and i + 1 < len(lines):
            name = _person(lines[i + 1])
            if name:
                return name
    m = re.search(
        r"\b(?:regards|thanks|cheers|grüße|merci|saludos|saluti|pozdrawiam)[,.!]?\s+([A-Z][a-zà-ÿ'-]{1,20})\s*$",
        text or "",
        re.I | re.M,
    )
    if m and _person(m.group(1)):
        return m.group(1)
    for line in lines[-4:]:
        name = _person(line)
        if name:
            return name
    if "<" in (sender or ""):
        display = sender.split("<")[0].strip().strip('"')
        name = _person(display) if display and "@" not in display else ""
        if name:
            return name
    local = sender_email(sender).split("@")[0]
    if re.fullmatch(r"[a-z]{2,20}[._][a-z]{2,30}", local):
        return local.split(".")[0].split("_")[0].title()
    return ""


def extract(subject: str, body: str, sender: str, rfq_id: str) -> Extracted:
    text = f"{subject}\n{fresh_text(body)}"
    language = lang.detect(fresh_text(body) or subject)
    stated = bool(FAST.search(text) or CHEAP.search(text))
    pref = "fastest" if FAST.search(text) and not CHEAP.search(text) else preference(None)
    origin, dest = find_route(text)
    pieces = find_pieces(text)
    gross, wunit = find_gross(text, pieces)
    lots = parse_lots(text)
    if lots and lots[1] > 0:
        pieces, gross, wunit = [], lots[1], "kg"
    door = bool(PICKUP.search(text)) and not SELF_DELIVERY.search(text)
    postcode = next((p for p in POSTCODE.findall(text)), None) if door else None
    zones = kit.pickup_zones()
    zone = postcode[:2] if postcode and postcode[:2] in zones else None
    if door and zone:
        zone_airport = zones[zone]["airport"]
        explicit = origin is not None and re.search(
            rf"\b(?:from|ex|origin\s*:?|departure\s*(?:airport)?\s*:?)\s+{origin}\b", text, re.I
        )
        if not explicit:
            origin = zone_airport

    vols = [volume_cbm_of(m) for m in VOLUME.finditer(text)]
    if not vols:
        vols = [
            num(m.group("v"))
            for m in UNIT_FIRST_VOLUME.finditer(text)
            if re.search(r"total", text[max(0, m.start() - 12) : m.start()], re.I)
        ][-1:]
    if len(vols) > 1 and len(LOT.findall(text)) > 1:
        volume = sum(vols, Decimal(0)) if not pieces else None
    else:
        volume = vols[0] if vols and not pieces else None
    counted = sum(p.count for p in pieces) or sum(
        int(m.group("n")) for m in COUNT_ONLY.finditer(text)
    )
    if not counted:
        label = re.search(
            r"(?:total )?(?:pieces|pcs|packages|colli|kolli|stück|anzahl)\s*[:=]\s*(\d{1,4})\b",
            text,
            re.I,
        )
        counted = int(label.group(1)) if label else 0
    if lots and lots[1] > 0:
        volume = lots[2] if lots[2] > 0 else volume
        counted = lots[0]
    missing = [k for k, v in (("origin", origin), ("destination", dest)) if not v]
    if gross is None and not (pieces and all(p.weight is not None for p in pieces)):
        missing.append("gross weight")
    shipment = None
    problems = []
    gross_kg = charge = None
    if not missing:
        shipment = Shipment(
            rfq_id=rfq_id,
            origin=origin,
            destination=dest,
            pieces=pieces,
            gross_weight=gross,
            weight_unit=wunit,
            volume_cbm=volume,
            preference=pref,
            door_pickup=door,
            pickup_zone=zone,
            pickup_postcode=postcode,
            lithium_un3480=bool(LITHIUM.search(text)),
            ready_date=find_ready(text),
            quote_currency=find_currency(text),
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
        tallest_cm=float(tallest_cm(text)) if tallest_cm(text) is not None else None,
    )
