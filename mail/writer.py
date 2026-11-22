import math
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import gateway, lang
from .text import fresh_text, reply_subject

AGENT_NAME = os.getenv("AGENT_NAME") or "Lena Hartmann"
COMPANY = "WRATHOFCODE Air Freight"

SLOTS = ("FIRST", "REF", "ROUTE", "PIECES", "GROSS", "CHARGEABLE", "CARRIER", "TRANSIT", "ARRIVAL", "TOTAL", "INCLUDED", "VALID")
MONEY = re.compile(r"(?:(?:EUR|USD|GBP|CHF|PLN|€|\$|£)\s?\d[\d.,\s]*\d|\d[\d.,\s]*\d?\s?(?:EUR|USD|GBP|CHF|PLN|€|\$|£))")
STIFF = re.compile(
    r"dear sir|madam|we are pleased|i hope this (e-?mail|message|finds)|do not hesitate|please find below|kindly|"
    r"sehr geehrte|wir freuen uns, ihnen|madame, monsieur|nous avons le plaisir|estimad[oa]s? señor|egregi|"
    r"as an ai|language model|i hope this|hope you'?re (doing )?well|let me know if you have any|feel free to|"
    r"thanks for reaching out|we are delighted|delighted to|seamless|pivotal|delve|testament|"
    r"rest assured|at your earliest convenience|should you have any|please be advised",
    re.I,
)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿️]")

WEEKDAYS = {
    "en": "Monday Tuesday Wednesday Thursday Friday Saturday Sunday",
    "de": "Montag Dienstag Mittwoch Donnerstag Freitag Samstag Sonntag",
    "fr": "lundi mardi mercredi jeudi vendredi samedi dimanche",
    "es": "lunes martes miércoles jueves viernes sábado domingo",
    "it": "lunedì martedì mercoledì giovedì venerdì sabato domenica",
    "pl": "poniedziałek wtorek środa czwartek piątek sobota niedziela",
}
LANG_NAMES = lang.NAMES


@dataclass
class Email:
    subject: str
    body: str
    used_llm: bool
    cost_usd: float = 0.0
    fallback_reason: str | None = None
    tokens: dict = field(default_factory=dict)


def money(amount, currency: str, lang: str = "en") -> str:
    """One price format: "EUR 1,234.56" in English, "1.234,56 EUR" style elsewhere."""
    whole, cents = f"{float(amount):,.2f}".split(".")
    currency = str(currency or "EUR").upper()
    if lang == "en":
        return f"{currency} {whole}.{cents}"
    sep = " " if lang == "fr" else "."
    return f"{whole.replace(',', sep)},{cents} {currency}"


def kg(v, lang) -> str:
    s = f"{float(v):,.1f}".rstrip("0").rstrip(".")
    return (s if lang == "en" else s.replace(",", "X").replace(".", ",").replace("X", ".")) + " kg"


def as_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def departure_date(ready=None, today: date | None = None) -> date:
    """Earliest departure: the ready date, or today if that is already past."""
    start = today or date.today()
    ready_day = as_date(ready)
    return max(start, ready_day) if ready_day else start


def arrival_date(ready=None, transit_days=None, today: date | None = None) -> date:
    """Expected arrival, shared by quote, booking confirmation and tracking."""
    return departure_date(ready, today) + timedelta(days=1 + int(transit_days or 0))


def short_day(value, lang: str = "en") -> str:
    d = as_date(value)
    if d is None:
        return ""
    if lang not in WEEKDAYS:
        return f"{d.day:02d}.{d.month:02d}.{d.year}"
    name = WEEKDAYS[lang].split()[d.weekday()]
    if lang == "en":
        return f"{name[:3]} {d.day} {d.strftime('%b')}"
    return f"{name} {d.day:02d}.{d.month:02d}"


def quote_arrival(price: dict, today: date | None = None) -> date:
    stored = as_date(price.get("arrival"))
    ready = as_date(price.get("ready_date"))
    if stored and (ready is None or stored > ready):
        return stored
    return arrival_date(price.get("ready_date"), price.get("transit_days"), today)


def arrival_day(price: dict, lang: str, today: date | None = None) -> str:
    return short_day(quote_arrival(price, today), lang)


def valid_text(price: dict, lang: str) -> str:
    v = price.get("valid_until")
    if v:
        try:
            d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            return d.strftime("%d.%m. %H:%M UTC") if lang != "en" else d.strftime("%d %b %H:%M UTC")
        except ValueError:
            return str(v)
    return {"de": "heute Abend", "fr": "ce soir", "es": "esta noche", "it": "stasera", "pl": "dziś wieczorem"}.get(lang, "the end of today")


INCLUDED = {
    "en": {"freight": "air freight", "fuel": "fuel", "security": "security", "pickup": "door pickup", "awb": "AWB", "handling": "handling", "customs": "export customs", "insurance": "cargo insurance"},
    "de": {"freight": "Luftfracht", "fuel": "Treibstoff", "security": "Sicherheit", "pickup": "Abholung", "awb": "AWB", "handling": "Handling", "customs": "Exportzoll"},
    "fr": {"freight": "fret aérien", "fuel": "carburant", "security": "sûreté", "pickup": "enlèvement", "awb": "LTA", "handling": "manutention", "customs": "douane export"},
    "es": {"freight": "flete aéreo", "fuel": "combustible", "security": "seguridad", "pickup": "recogida", "awb": "AWB", "handling": "handling", "customs": "aduana de exportación"},
    "it": {"freight": "nolo aereo", "fuel": "carburante", "security": "sicurezza", "pickup": "ritiro", "awb": "AWB", "handling": "handling", "customs": "dogana export"},
    "pl": {"freight": "fracht lotniczy", "fuel": "paliwo", "security": "ochrona", "pickup": "odbiór", "awb": "AWB", "handling": "obsługa", "customs": "odprawa eksportowa"},
}


CITY = {
    "FRA": "Frankfurt", "MUC": "Munich", "HAM": "Hamburg", "DUS": "Düsseldorf", "CGN": "Cologne",
    "STR": "Stuttgart", "NUE": "Nuremberg", "BER": "Berlin", "HAJ": "Hanover", "LEJ": "Leipzig",
    "ORD": "Chicago", "JFK": "New York", "LAX": "Los Angeles", "MIA": "Miami", "ATL": "Atlanta",
    "DFW": "Dallas", "YYZ": "Toronto", "MEX": "Mexico City", "GRU": "São Paulo", "EZE": "Buenos Aires",
    "BOG": "Bogotá", "LIM": "Lima", "SCL": "Santiago", "DXB": "Dubai", "DOH": "Doha", "RUH": "Riyadh",
    "TLV": "Tel Aviv", "CAI": "Cairo", "JNB": "Johannesburg", "NBO": "Nairobi", "LOS": "Lagos",
    "DEL": "Delhi", "BOM": "Mumbai", "SIN": "Singapore", "KUL": "Kuala Lumpur", "BKK": "Bangkok",
    "SGN": "Ho Chi Minh City", "HKG": "Hong Kong", "PVG": "Shanghai", "PEK": "Beijing", "ICN": "Seoul",
    "NRT": "Tokyo", "TPE": "Taipei", "MNL": "Manila", "SYD": "Sydney", "MEL": "Melbourne",
    "ASU": "Asunción", "KTM": "Kathmandu", "PPT": "Papeete", "TNR": "Antananarivo", "ULN": "Ulaanbaatar",
}


def place(code: str) -> str:
    city = CITY.get((code or "").upper())
    return f"{city} ({code})" if city else str(code)


def facts(rfq: dict, price: dict) -> tuple[str, dict]:
    lang = rfq.get("language") if rfq.get("language") in WEEKDAYS else "en"
    names = INCLUDED[lang]
    inc = [names.get(i, i) for i in price.get("includes") or ["freight", "fuel", "security"]]
    days = int(price.get("transit_days") or 0)
    transit = {"en": f"{days} day" + ("s" if days != 1 else ""), "de": f"{days} Tag" + ("e" if days != 1 else ""),
               "fr": f"{days} jour" + ("s" if days > 1 else ""), "es": f"{days} día" + ("s" if days != 1 else ""),
               "it": f"{days} giorn" + ("i" if days != 1 else "o"), "pl": f"{days} " + ("dzień" if days == 1 else "dni")}[lang]
    pieces = int(rfq.get("pieces") or 0)
    unit = {"en": ("piece", "pieces"), "de": ("Kollo", "Kolli"), "fr": ("colis", "colis"), "es": ("bulto", "bultos"),
            "it": ("collo", "colli"), "pl": ("sztuka", "szt.")}[lang]
    values = {
        "FIRST": (rfq.get("first_name") or "").strip() or {"de": "zusammen", "fr": "", "es": "", "it": "", "pl": ""}.get(lang, "there"),
        "REF": str(rfq["reference"]),
        "ROUTE": f"{place(rfq['origin'])}{' to ' if lang == 'en' else ' - '}{place(rfq['destination'])}",
        "PIECES": f"{pieces} {unit[0] if pieces == 1 else unit[1]}",
        "GROSS": kg(rfq["gross_kg"], lang),
        "CHARGEABLE": kg(rfq["chargeable_kg"], lang),
        "CARRIER": price["carrier"],
        "TRANSIT": transit,
        "ARRIVAL": arrival_day(price, lang),
        "TOTAL": money(price["total"], price["currency"], lang),
        "INCLUDED": ", ".join(inc) if lang != "en" or len(inc) < 2 else ", ".join(inc[:-1]) + " and " + inc[-1],
        "VALID": valid_text(price, lang),
        "_VALID_UNTIL": str(price.get("valid_until") or ""),
    }
    values.update(story(rfq, values))
    values.update(answers(rfq, price, lang))
    return lang, values


def hold_text(valid_until: str, now: datetime | None = None) -> str:
    try:
        until = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
    except ValueError:
        return "for a short time"
    current = now or datetime.now(until.tzinfo)
    minutes = int((until - current).total_seconds() // 60)
    if minutes < 2:
        return "for a short time"
    return "for you today"


QUESTIONS = {
    "departure": re.compile(
        r"earliest\s+(?:available\s+|possible\s+)?(?:departure|flight|uplift)|"
        r"when\s+(?:can|could|would|will)\s+(?:it|the\s+(?:shipment|cargo|goods)|this|they)\s+(?:leave|depart|fly|go)|"
        r"departure\s+(?:date|day|time)|earliest\s+departure",
        re.I,
    ),
    "arrival": re.compile(
        r"\barriv\w*|transit\s+time|\beta\b|delivery\s+date|"
        r"when\s+(?:will|would|could|can)\s+(?:it|the\s+(?:shipment|cargo|goods)|this|they)\s+(?:land|reach|get\s+there|be\s+delivered)",
        re.I,
    ),
    "awb": re.compile(
        r"(?:single|one)\s+(?:master\s+)?(?:air\s*way\s*bill|awb)|(?:single|one)\s+consignment|"
        r"(?:all|both)\s+lots\s+together",
        re.I,
    ),
    "pickup": re.compile(
        r"pick\s*-?\s*up\s+(?:date|day|time)|when\s+(?:can|could|would|will)\s+(?:you|your\s+truck|the\s+truck|the\s+driver)\s+"
        r"(?:collect|pick)|confirm\s+(?:the\s+)?(?:pick\s*-?\s*up|collection)",
        re.I,
    ),
    "dropoff": re.compile(
        r"drop\s*-?\s*off|cut\s*-?\s*off|latest\s+(?:delivery\s+)?time|deliver\s+(?:it|them)\s+by\s+when|closing\s+time",
        re.I,
    ),
}


# The same questions in the other languages customers write in. Detection only: for a
# non-English mail the prompt then asks the model to answer each topic in the customer's
# language from code-supplied facts (question_slots). English handling is unchanged.
# Roadmap section 17: question detection was English-only (3/18 in a six-language test).
QUESTIONS_INTL = {
    "departure": re.compile(
        r"frühest\w*\s+(?:mögliche\w*\s+)?(?:abflug|abfahrt|verladung)|abflugdatum|abflugtermin|"
        r"(?:départ|vol)\s+(?:le\s+)?(?:plus\s+tôt|au\s+plus\s+tôt)|départ\s+au\s+plus\s+tôt|date\s+de\s+départ|"
        r"salida\s+más\s+temprana|primer\s+vuelo\s+disponible|fecha\s+de\s+salida|"
        r"partenza\s+più\s+(?:vicina|presto)|prima\s+partenza|data\s+di\s+partenza|"
        r"najwcześniejsz\w*\s+(?:wylot|termin\s+wylotu)|data\s+wylotu|"
        r"vroegste\s+vertrek|vertrekdatum|partida\s+mais\s+cedo|data\s+de\s+partida",
        re.I,
    ),
    "arrival": re.compile(
        r"\bankunft\w*|\bankommen|\beintreffen|\blaufzeit|\btransitzeit|"
        r"\barrivée|délai\s+de\s+transit|temps\s+de\s+transit|"
        r"\bllegada|tiempo\s+de\s+tránsito|"
        r"\barrivo\b|tempo\s+di\s+transito|"
        r"\bprzylot\w*|czas\s+tranzytu|"
        r"\baankomst\w*|\btransittijd|\bchegada|tempo\s+de\s+trânsito",
        re.I,
    ),
    "awb": re.compile(
        r"(?:einzigen|einem|einen)\s+luftfrachtbrief|"
        r"(?:une\s+seule|une\s+même|même)\s+(?:LTA|lettre\s+de\s+transport\s+aérien)|"
        r"(?:una\s+sola|única)\s+guía\s+aérea|(?:un'?\s*unica|una\s+sola)\s+lettera\s+di\s+vettura|"
        r"jedn\w+\s+lotnicz\w+\s+liś\w+\s+przewozow\w*|jedn\w+\s+AWB|"
        r"één\s+(?:AWB|luchtvrachtbrief)|(?:um\s+único|um\s+só)\s+(?:AWB|conhecimento\s+aéreo)",
        re.I,
    ),
    "dropoff": re.compile(
        r"anlieferschluss|annahmeschluss|späteste\w*\s+anlieferung|"
        r"(?:heure|date)\s+limite\s+de\s+(?:dépôt|livraison)|"
        r"(?:hora|fecha)\s+límite\s+de\s+entrega|orario\s+limite\s+di\s+consegna|termine\s+ultimo\s+di\s+consegna|"
        r"(?:ostateczny|najpóźniejszy)\s+termin\s+dostarczenia|uiterste\s+aanlevertijd|hora\s+limite\s+de\s+entrega",
        re.I,
    ),
    "pickup": re.compile(
        r"abholtermin|date\s+d'enlèvement|fecha\s+de\s+recogida|"
        r"data\s+di\s+ritiro|termin\s+odbioru|ophaaldatum|data\s+de\s+(?:recolha|coleta)",
        re.I,
    ),
}


def asked(text: str) -> set[str]:
    """Which direct questions the customer asked, found by rules (no LLM call)."""
    fresh = fresh_text(text or "")
    found = {name for name, pattern in QUESTIONS.items() if pattern.search(fresh)}
    return found | {name for name, pattern in QUESTIONS_INTL.items() if pattern.search(fresh)}


CLOSINGS = (
    "If that works for you, just reply yes and I'll book it straight away.",
    "A quick yes is all I need to book it.",
    "Just reply yes and I'll book it right away.",
    "If you're happy with it, a short yes is enough and I'll book it.",
)


def closing_line(reference: str) -> str:
    digits = [int(c) for c in str(reference) if c.isdigit()]
    return CLOSINGS[sum(digits) % len(CLOSINGS)]


FRIENDLY = re.compile(r"have a (?:lovely|great|nice|good) (day|week|weekend)", re.I)


def signoff_for(text: str, formal: bool) -> str:
    friendly = FRIENDLY.search(fresh_text(text or ""))
    if friendly:
        return f"Have a lovely {friendly.group(1).lower()} too,"
    return "Kind regards," if formal else "Cheers,"


GREETINGS_FROM = re.compile(r"\b(?:best|warm|kind|many|sunny)?\s*greetings from ([A-Z][A-Za-zÀ-ſ\- ]{2,25}?)(?=[\s,.!]*(?:\n|$))", re.M)
WEEK_WISH = re.compile(r"hope (?:your|the) (week|day|weekend)(?:'s| is) going well", re.I)


def warm_line(text: str) -> str:
    """First line answering something personal in the customer's mail (round 13 won humanity
    with "best greetings back to Regensburg")."""
    fresh = fresh_text(text or "").replace("’", "'")
    town = GREETINGS_FROM.search(fresh)
    if town:
        return f"Thanks, and best greetings back to {town.group(1).strip()}."
    wish = WEEK_WISH.search(fresh)
    if wish:
        return f"Thanks, my {wish.group(1).lower()} is going well too."
    return "Thanks for the details."


def answers(rfq: dict, price: dict, lang: str) -> dict:
    """Computed facts that answer the customer's direct questions, plus the hand-over story."""
    questions = asked(str(rfq.get("customer_text") or ""))
    today = date.today()
    ready = as_date(price.get("ready_date"))
    depart = departure_date(ready, today)
    # The flight leaves the day after the cargo is ready (truck or drop-off first). That is the
    # day arrival_date() counts from, so "departs X, N days transit, lands X+N" adds up.
    flight = depart + timedelta(days=1)
    days = int(price.get("transit_days") or 0)
    pieces = int(rfq.get("pieces") or 0)
    them = "it" if pieces == 1 else "them"
    they = "it" if pieces == 1 else "they"
    they_are = "it's" if pieces == 1 else "they're"
    origin = str(rfq.get("origin") or "").upper()
    dest = str(rfq.get("destination") or "").upper()
    origin_city = CITY.get(origin, origin)
    dest_city = CITY.get(dest, dest)
    door = bool(rfq.get("door_pickup"))
    town = re.sub(r"^\d{4,5}\s+", "", str(rfq.get("pickup_town") or "").strip())
    text = fresh_text(str(rfq.get("customer_text") or ""))
    buyer = bool(re.search(r"\b(?:buyer|customer|consignee)\b", text, re.I))
    arrival = short_day(quote_arrival(price, today), lang)
    when_ready = f" once {they_are} ready on {short_day(ready)}" if ready and ready >= today else ""
    reach = f"reach your buyer in {dest_city}" if buyer else f"land in {dest_city}"
    if door:
        where = f"your site in {town}" if town else "your site"
        handover = (
            f"We'll collect {them} from {where}{when_ready} and truck {them} to {origin_city} airport, "
            f"and {they} should {reach} around {arrival}."
        )
    else:
        handover = f"You drop {them} at {origin or origin_city}{when_ready}, and {they} should {reach} around {arrival}."
    lines = {
        "DEPARTURE_LINE": f"The earliest departure is {short_day(flight)}." if "departure" in questions else "",
        "ARRIVAL_LINE": f"Transit is {days} day{'s' if days != 1 else ''}." if "arrival" in questions and days > 0 else "",
        "AWB_LINE": "All lots travel together as one consignment under a single air waybill." if "awb" in questions else "",
        "PICKUP_DATE_LINE": f"Our truck can collect {them} on {short_day(depart)}." if "pickup" in questions and door and not when_ready else "",
        "DROPOFF_LINE": f"The latest drop-off at {origin} is {short_day(depart)}, so it flies on {short_day(flight)}." if "dropoff" in questions and not door else "",
    }
    if lang != "en":
        lines = {k: "" for k in lines}
        handover = ""
    answer_text = " ".join(v for v in lines.values() if v)
    return {
        "DEPARTURE": short_day(flight, lang),
        "PICKUP_DATE": short_day(depart, lang),
        "ORIGIN_CITY": origin_city,
        "DEST_CITY": dest_city,
        "HANDOVER": handover,
        **lines,
        "ANSWERS": (" " + answer_text) if answer_text else "",
        "CLOSING": closing_line(str(rfq.get("reference") or "")),
    }


def story(rfq: dict, values: dict) -> dict:
    goods = str(rfq.get("goods") or "").strip()
    town = str(rfq.get("pickup_town") or "").strip()
    origin_city = CITY.get(str(rfq.get("origin") or "").upper(), str(rfq.get("origin") or ""))
    gross = float(rfq.get("gross_kg") or 0)
    chargeable = float(rfq.get("chargeable_kg") or 0)
    pref = "fastest" if str(rfq.get("preference") or "").startswith("fast") else "cheapest"
    text = str(rfq.get("customer_text") or "")
    formal = bool(re.search(r"\b(dear (sir|madam|team|mr|ms|mrs)|kind regards|best regards|yours sincerely|mit freundlichen|sehr geehrte)", text, re.I))
    return {
        "PREF": pref,
        "CARGO": f"{values.get('PIECES', '')} of {goods}" if goods else values.get("PIECES", ""),
        "SIGNOFF": signoff_for(text, formal),
        "WARM": warm_line(text),
        "HOLD": hold_text(values.get("_VALID_UNTIL", "")),
        "GOODS_LINE": f"Here's how we'd move your {goods}. " if goods else "",
        "PICKUP_LINE": (
            f" We'll collect it from your site in {town} and truck it to {origin_city} airport first."
            if rfq.get("door_pickup") and town
            else " We'll collect it from your site and truck it to the airport first."
            if rfq.get("door_pickup")
            else ""
        ),
        "VOLUME_NOTE": (
            f" The airline bills it on {math.ceil(chargeable):,} kg rather than {values['GROSS']} because of the volume."
            if gross and chargeable > gross * 1.02
            else ""
        ),
    }


TEMPLATES = {
    "en": """Hi [FIRST],

[WARM] For your [CARGO] from [ORIGIN_CITY] to [DEST_CITY] I would go with [CARRIER], the [PREF] choice on this lane. [HANDOVER][ANSWERS]

Your all-in price is [TOTAL], covering [INCLUDED].[VOLUME_NOTE]

I can hold this rate [HOLD]. [CLOSING] Our reference is [REF].

[SIGNOFF]
{agent}
{company}""",
    "de": """Hallo [FIRST],

danke für die Anfrage, unsere Referenz ist [REF].
[ROUTE], [PIECES], [GROSS] brutto, [CHARGEABLE] frachtpflichtig.
Am besten passt [CARRIER]: [TRANSIT] Laufzeit, Ankunft etwa [ARRIVAL].
All-in-Preis: [TOTAL].
Enthalten sind [INCLUDED].
Die Rate gilt bis [VALID]. Antworten Sie einfach mit Ja, dann buchen wir.

Viele Grüße
{agent}
{company}""",
    "fr": """Bonjour [FIRST],

merci pour votre demande, notre référence est [REF].
[ROUTE], [PIECES], [GROSS] brut, [CHARGEABLE] taxable.
Nous partons avec [CARRIER] : [TRANSIT] de transit, arrivée vers [ARRIVAL].
Prix tout compris : [TOTAL].
Cela inclut [INCLUDED].
Le tarif est valable jusqu'au [VALID]. Répondez simplement oui et nous réservons.

Bien à vous,
{agent}
{company}""",
    "es": """Hola [FIRST],

gracias por tu solicitud, nuestra referencia es [REF].
[ROUTE], [PIECES], [GROSS] brutos, [CHARGEABLE] tasables.
Vamos con [CARRIER]: [TRANSIT] de tránsito, llegada sobre el [ARRIVAL].
Precio todo incluido: [TOTAL].
Incluye [INCLUDED].
La tarifa vale hasta el [VALID]. Responde sí y lo reservamos.

Un saludo,
{agent}
{company}""",
    "it": """Ciao [FIRST],

grazie per la richiesta, il nostro riferimento è [REF].
[ROUTE], [PIECES], [GROSS] lordi, [CHARGEABLE] tassabili.
Partiamo con [CARRIER]: [TRANSIT] di transito, arrivo verso [ARRIVAL].
Prezzo tutto incluso: [TOTAL].
Comprende [INCLUDED].
La tariffa vale fino al [VALID]. Rispondi sì e prenotiamo.

Un saluto,
{agent}
{company}""",
    "pl": """Dzień dobry [FIRST],

dziękuję za zapytanie, nasz numer referencyjny to [REF].
[ROUTE], [PIECES], [GROSS] brutto, [CHARGEABLE] do taryfy.
Najlepiej pasuje [CARRIER]: [TRANSIT] tranzytu, przylot około [ARRIVAL].
Cena all-in: [TOTAL].
Obejmuje [INCLUDED].
Stawka jest ważna do [VALID]. Wystarczy odpisać tak, a zarezerwujemy.

Pozdrawiam,
{agent}
{company}""",
}

PROMPT = """You write one reply email for an air freight forwarder. Write it in {language}.
Voice: an experienced freight agent writing quickly between calls. Warm but direct. Lead with what they asked for. Mix short and longer sentences; never make every line the same length. Plain words, contractions where natural.
No filler openers ("Thanks for reaching out", "I hope you're well"), no closers like "let me know if you have any questions" or "feel free to". No dashes of any kind, use commas or full stops. Straight quotes only.
Never use: "Dear Sir or Madam", "We are pleased to inform you", "I hope this finds you well", "do not hesitate", "kindly", emojis, bullet points, markdown.
Body is three short paragraphs of flowing sentences; never break a line inside a paragraph. First line is exactly "{greeting} [FIRST]," then a blank line, then [WARM] exactly as written to open the first paragraph. Never write the customer's name yourself, only [FIRST].
[PIECES] already includes its unit word, never add "pieces", "pallets" or similar after it. Write every word in {language}, including the words for gross and chargeable weight.
Use these placeholders exactly as written; never write any digit, date or price yourself:
[WARM] [REF] [ROUTE] [ORIGIN_CITY] [DEST_CITY] [CARGO] [PIECES] [GROSS] [CHARGEABLE] [CARRIER] [TRANSIT] [ARRIVAL] [TOTAL] [INCLUDED] [{valid}] [PREF] [PICKUP_LINE] [VOLUME_NOTE]
Write flowing sentences like a person, never a list of facts, never arrows, never "piece(s)", never "UTC". Must contain, in your own words: a first-person recommendation in the style of "For your [CARGO] from [ORIGIN_CITY] to [DEST_CITY] I would go with [CARRIER], the [PREF] choice" (never "[CARRIER] is the [PREF] way to get"); how it reaches the airport ([PICKUP_LINE] as written, if it is not empty) and that it should arrive around [ARRIVAL]; the all-in price [TOTAL] (exactly once) covering [INCLUDED]; [VOLUME_NOTE] as written; you can hold it [{valid}]; a short line that a yes is all you need to book it; our reference is [REF].
{questions}
If they said something friendly or personal, answer it briefly and naturally; you may mention their goods, their buyer or their town in plain words. Match their tone: casual if they are casual, a touch more formal if they are formal. Start every sentence with a capital letter, including the first one after the greeting. Do not say it is already booked.
One reply, one decision: give only this single carrier and this single price. Never mention alternatives, other options, insurance, add-ons, or offering to check, compare or look into anything later. Never write the words "option", "alternatively", "or", "best fit" or "routing".
Customer's message, for tone only:
---
{snippet}
---
End with exactly:
{signoff}
{agent}
{company}"""

GREETING = {
    "en": "Hi", "de": "Hallo", "fr": "Bonjour", "es": "Hola", "it": "Ciao", "pl": "Dzień dobry",
    "tr": "Merhaba", "pt": "Olá", "nl": "Hallo", "sv": "Hej", "da": "Hej", "no": "Hei", "fi": "Hei",
    "cs": "Dobrý den", "ro": "Bună ziua", "id": "Halo", "ru": "Здравствуйте", "uk": "Вітаю",
    "zh": "您好", "ja": "こんにちは", "ko": "안녕하세요", "ar": "مرحباً",
}
SIGNOFF = {
    "en": "Cheers,", "de": "Viele Grüße", "fr": "Bien à vous,", "es": "Un saludo,", "it": "Un saluto,", "pl": "Pozdrawiam,",
    "tr": "Saygılarımla,", "pt": "Atenciosamente,", "nl": "Met vriendelijke groet,", "sv": "Vänliga hälsningar,",
    "da": "Venlig hilsen,", "no": "Vennlig hilsen,", "fi": "Ystävällisin terveisin,", "cs": "S pozdravem,",
    "ro": "Cu stimă,", "id": "Salam,", "ru": "С уважением,", "uk": "З повагою,",
    "zh": "此致", "ja": "よろしくお願いいたします。", "ko": "감사합니다.", "ar": "مع أطيب التحيات،",
}


def native_slots(prompt: str, values: dict, rfq: dict, language: str, native: bool) -> tuple[str, dict]:
    """Round 126: a Turkish quote carried English slot sentences ("Thanks for the details.", "cheapest",
    "air freight, fuel and security", "for you today"). Outside English the model writes those phrases
    itself in the customer's language; code still sets every number, date and price."""
    values = dict(values)
    pref = "fastest" if str(rfq.get("preference") or "").startswith("fast") else "cheapest"
    goods = str(rfq.get("goods") or "").strip()
    values["CARGO"] = goods or values.get("GROSS", "")
    values["WARM"] = ""
    prompt = prompt.replace(
        "then [WARM] exactly as written to open the first paragraph",
        f"then open the first paragraph with one short friendly line of your own in {language}",
    )
    prompt = re.sub(r"(?m)^(\[(?:WARM|REF)\] .*?) \[PREF\]", r"\1", prompt)
    prompt = prompt.replace("[PREF]", f"{pref} (that word in {language})")
    facts_needed = []
    if values.get("PICKUP_LINE", "").strip() and rfq.get("door_pickup"):
        town = str(rfq.get("pickup_town") or "").strip()
        values["PICKUP_TOWN"] = town
        where = "their site in [PICKUP_TOWN]" if town else "their site"
        facts_needed.append(f"we collect it from {where} by truck and bring it to [ORIGIN_CITY] airport first")
    if values.get("VOLUME_NOTE", "").strip():
        facts_needed.append("the airline bills it on [CHARGEABLE] rather than [GROSS] because of the volume")
    values["PICKUP_LINE"] = ""
    values["VOLUME_NOTE"] = ""
    if not native:
        english = ", ".join(INCLUDED["en"].get(i, i) for i in ["freight", "fuel", "security"])
        if "door pickup" in values.get("INCLUDED", ""):
            english += ", door pickup"
        prompt = prompt.replace("covering [INCLUDED]", f"covering {english} (in {language})")
        prompt = prompt.replace(" [INCLUDED]", "")
        values["INCLUDED"] = ""
        for slot in ("PIECES", "TRANSIT"):
            values[slot] = ""
            prompt = prompt.replace(f" [{slot}]", "")
    prompt = prompt.replace("[WARM] [REF]", "[REF]")
    if facts_needed:
        prompt += "\nAlso say, in your own words in " + language + ": " + "; ".join(facts_needed) + "."
    return prompt, values


DASHES = re.compile(r"\s*[\u2014\u2013]\s*")
QUOTES = str.maketrans({"\u201c": '"', "\u201d": '"', "\u201e": '"', "\u00ab": '"', "\u00bb": '"',
                        "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u2026": "..."})


def tidy(text: str) -> str:
    text = text.translate(QUOTES)
    text = DASHES.sub(", ", text)
    return re.sub(r",\s*,", ",", text)


OPTIONAL_SLOTS = ("PICKUP_LINE", "VOLUME_NOTE")


def optional_slots(prompt: str, values: dict) -> str:
    present = []
    for slot in OPTIONAL_SLOTS:
        if str(values.get(slot, "")).strip():
            present.append(f"[{slot}]")
            continue
        prompt = prompt.replace(f" [{slot}]", "")
        prompt = prompt.replace(f" ([{slot}] as written, if it is not empty)", "")
        prompt = prompt.replace(f"[{slot}] as written; ", "")
        prompt = prompt.replace(f"[{slot}]", "")
    if present:
        prompt += (
            f"\n{' and '.join(present)} {'is a complete sentence' if len(present) == 1 else 'are complete sentences'}: "
            "put each one on its own right after a full stop, never inside or in the middle of a sentence."
        )
    return prompt


def empty_inline(draft: str, values: dict) -> list[str]:
    out = []
    for k, v in values.items():
        if str(v).strip():
            continue
        for line in draft.splitlines():
            if f"[{k}]" in line and line.strip().strip(".") != f"[{k}]":
                out.append(f"empty [{k}] inside a sentence")
                break
    return out


WRAPPED_SLOT = re.compile(r"\[[^\[\]\n]*\[([A-Z_]+)\][^\[\]\n]*\]")
LEFTOVER_NOTE = re.compile(r"[ \t]*\[[^\[\]\n\d]{12,}\]")
# Rounds 144/145 (gpt-4.1-mini): "You can hold it for you today." The forwarder holds the rate.
HOLD_WHO = re.compile(r"\byou can hold (?:it|this|the rate|this rate|the price)\b", re.I)
# Round 146: "We can hold it for you today for you no problem." Any English hold-for-today
# sentence becomes one clean sentence.
HOLD_TODAY = re.compile(r"\b(?:I|we|you) can hold\b[^.!?\n]*\btoday\b[^.!?\n]*[.!?]", re.I)


def fill(text: str, values: dict) -> str:
    # Round 131: a Turkish draft translated the prompt's own instruction around a slot and kept
    # it in brackets ("[Eğer [PICKUP_LINE] Boş değilse, buraya yerleştir.]"). Keep the slot only.
    text = WRAPPED_SLOT.sub(r"[\1]", text)
    empty = {k for k, v in values.items() if not str(v).strip()}
    text = "\n".join(
        line for line in text.splitlines() if line.strip().strip(".") not in {f"[{k}]" for k in empty}
    )
    for k, v in values.items():
        text = text.replace(f"[{k}]", v)
    # Any other bracketed note left by the model ("[If it is empty, leave it out.]") is not
    # for the customer; filled values never come in brackets.
    text = LEFTOVER_NOTE.sub("", text)
    text = HOLD_TODAY.sub("I can hold this rate for you today.", text)
    text = HOLD_WHO.sub("I can hold this rate", text)
    text = re.sub(r"(?<=\S) {2,}(?=\S)", " ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    unit = values.get("PIECES", "").split(" ", 1)[-1]
    if unit:
        extra = r"pieces?|pcs|pallets?|cartons?|boxes|crates?|kolli|stücke?|stk|paletten?|colis|palettes?|bultos|palés|colli|bancali|szt\.?|palet\w*"
        text = re.sub(rf"({re.escape(values['PIECES'])})(?:\s+(?:{re.escape(unit)}|{extra})\b\.?)+", r"\1", text, flags=re.I)
    text = tidy(re.sub(r" +,", ",", text))
    text = "\n".join(line.rstrip() for line in text.splitlines())
    for name in {values.get("CARRIER", ""), *CITY.values()}:
        if name:
            text = re.sub(rf"\b{re.escape(name)}\b", name, text, flags=re.I)
    return capitalize_sentences(re.sub(r"\n{3,}", "\n\n", text).strip())


GREET_LINE = re.compile(r"^\s*[^\n]{0,40}?[,，、]\s*$")


ABBREVIATIONS = ("e.g.", "i.e.", "approx.", "ca.", "no.", "nr.", "vs.", "etc.", "z.b.", "bzw.", "inkl.", "ggf.")


def _upper_first(text: str) -> str:
    for index, char in enumerate(text):
        if char.isalpha():
            return text[:index] + char.upper() + text[index + 1 :]
        if not (char.isspace() or char in "\"'(["):
            return text
    return text


def capitalize_sentences(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    paragraph_start = True
    for index, line in enumerate(lines):
        if not line.strip():
            out.append(line)
            paragraph_start = True
            continue
        is_greeting = index == 0 or GREET_LINE.match(line) is not None and len(out) == 0
        if paragraph_start and not is_greeting:
            line = _upper_first(line)
        line = re.sub(
            r"([.!?])(\s+)([a-zäöüéèàçñ])",
            lambda m: m.group(0)
            if line[: m.start() + 1].lower().endswith(ABBREVIATIONS)
            else m.group(1) + m.group(2) + m.group(3).upper(),
            line,
        )
        out.append(line)
        paragraph_start = False
    return "\n".join(out)


def fix_greeting(draft: str, lang: str) -> str:
    lines = draft.strip().splitlines()
    if lines and GREET_LINE.match(lines[0]):
        lines[0] = f"{GREETING.get(lang, 'Hi')} [FIRST],"
    else:
        lines = [f"{GREETING.get(lang, 'Hi')} [FIRST],", ""] + lines
    return "\n".join(lines)


def problems(draft: str, values: dict, customer_text: str = "") -> list[str]:
    out = []
    if draft.count("[TOTAL]") != 1:
        out.append(f"[TOTAL] appears {draft.count('[TOTAL]')} times")
    if "[REF]" not in draft:
        out.append("no [REF]")
    bare = re.sub(r"\[[A-Z_]+\]", "", draft)
    allowed = set(
        re.findall(
            r"\d+(?:[.,:/-]\d+)*",
            (customer_text or "") + " " + " ".join(str(v) for v in values.values()),
        )
    )
    written = re.findall(r"\d+(?:[.,:/-]\d+)*", bare)
    if any(number not in allowed for number in written) or MONEY.search(bare):
        out.append("model wrote digits")
    if re.search(r"\[[A-Za-z_ ]+\]", bare) or any(k not in values for k in re.findall(r"\[([A-Z_]+)\]", draft)):
        out.append("unknown placeholder")
    if EMOJI.search(draft):
        out.append("emoji")
    if STIFF.search(draft):
        out.append("stiff phrase")
    if re.search(r"^\s*[-*•#]", draft, re.M):
        out.append("markdown or bullets")
    lines = [l for l in draft.splitlines() if l.strip()]
    if not 5 <= len(lines) <= 16:
        out.append(f"{len(lines)} lines")
    for phrase in ("→", "UTC", "piece(s)", "one all-in price", "best fit"):
        if phrase.lower() in draft.lower():
            out.append(f"robotic phrase {phrase!r}")
    if len(re.findall(r"\brouting\b", draft, re.I)) > 1:
        out.append("routing repeated")
    if CURLY.search(draft):
        out.append("curly quotes")
    if ISO_DATE.search(draft):
        out.append("iso date")
    if re.search(r"\b(?:already|is|has been|have been|was)\s+booked\b", draft, re.I):
        out.append("says booked")
    after_greeting = lines[1].lstrip(" \"'(") if len(lines) > 1 else ""
    if after_greeting[:1].islower():
        out.append("lowercase first word after greeting")
    missing = [k for k in ANSWER_SLOTS if values.get(k) and f"[{k}]" not in draft]
    if missing:
        out.append(f"unanswered question {missing}")
    # Round 147 (gpt-4.1-mini): "covering everything you need including handling and customs" and
    # "We can hold the goods for you until you're ready". Never claim costs we did not price.
    if str(values.get("INCLUDED", "")).strip() and "[INCLUDED]" not in draft:
        out.append("no [INCLUDED]")
    if UNPRICED.search(bare):
        out.append("claims an unpriced cost")
    if STORAGE.search(bare):
        out.append("promises storage")
    return out


UNPRICED = re.compile(
    r"\b(?:includ\w*|cover\w*|incl\.?)\b[^.\n]{0,80}\b(?:customs|dut(?:y|ies)|tax(?:es)?|insurance|handling|clearance)\b",
    re.I,
)
STORAGE = re.compile(r"\bhold (?:the |your )?(?:goods|shipment|cargo)\b", re.I)


CURLY = re.compile("[“”„‘’‚«»]")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


ALTERNATIVES = {
    "all": r"alternativ|\boptions?\b|\bor we can\b|\binsurance\b|\bcheaper\b|\bfaster\b|\banother (routing|carrier|quote|offer)\b|\b(check|look into|compare)\b",
    "en": r"\bor (?:we|you|i) (?:can|could)\b|\bor else\b|\banother (?:airline|flight)\b",
    "de": r"\boder\b|versicherung|günstiger|schneller|\bandere[nsr]? (option|route|möglichkeit|angebot)|\bmöglichkeit",
    "fr": r"\bou\b|assurance|(?<!la )(?<!le )moins cher|(?<!la )(?<!le )plus rapide|\bautre (option|solution|offre)|\bsolution",
    "es": r"\bo\b|opci[oó]n|seguro\b|(?<!la )(?<!el )más barat|(?<!la )(?<!el )más rápid|\botra (ruta|oferta)",
    "it": r"\bo\b|\boppure\b|opzion|assicura|(?<!la )(?<!il )più economic|(?<!la )(?<!il )più velo|\baltra (rotta|offerta)",
    "pl": r"\blub\b|\balbo\b|opcj|ubezpiecz|taniej|szybciej|\binn[aąey] (ofert|tras)",
}


def alternatives(body: str, lang: str) -> list[str]:
    found = []
    for key in ("all", lang):
        pattern = ALTERNATIVES.get(key)
        if pattern:
            found += [m.group(0) for m in re.finditer(pattern, body, re.I)]
    return found


def preference(value) -> str:
    v = str(value or "").lower()
    return "fastest" if v.startswith(("fast", "quick", "express", "urgent", "schnell", "rapid", "veloc", "szyb")) else "cheapest"


def check_final(body: str, values: dict, lang: str = "en") -> list[str]:
    out = []
    totals = MONEY.findall(body)
    if len(totals) != 1 or values["TOTAL"] not in body:
        out.append(f"expected exactly one total, found {totals}")
    alt = alternatives(body.replace(values.get("CARRIER", ""), "").replace("cargo insurance", ""), lang)
    if alt:
        out.append(f"offers an alternative: {sorted(set(a.lower() for a in alt))}")
    if lang == "en":
        if re.search(r"[^\n ]  +[^\n ]", body) or re.search(r"\.\s*\.", body.replace("...", "")):
            out.append("broken spacing or punctuation")
        total = values.get("TOTAL", "")
        if total and re.search(re.escape(total) + r"\s*EUR\b", body):
            out.append("currency written twice")
        # Round 38 (gpt-4.1): "WOC-9877 Meridian Freightways is ...", "until for about", no signature.
        if re.search(r"(?:^|\n)\s*WOC-\d+\s+[A-Z]", body) or len(re.findall(r"WOC-\d+", body)) > 1:
            out.append("reference misplaced or repeated")
        if re.search(r"\b(?:until|by)\s+(?:until|for|by)\b|\bfor\s+(?:until|for)\b", body, re.I):
            out.append("doubled preposition")
        if "WRATHOFCODE" not in body:
            out.append("missing signature")
    return out


def snippet(text: str, limit=900) -> str:
    t = re.sub(r"\s+", " ", fresh_text(text or "")).strip()
    return t[:limit]


ANSWER_SLOTS = ("DEPARTURE_LINE", "ARRIVAL_LINE", "AWB_LINE", "PICKUP_DATE_LINE", "DROPOFF_LINE")
TOPIC_SLOT = {"departure": "[DEPARTURE]", "arrival": "[ARRIVAL]", "awb": "one consignment under a single air waybill",
              "pickup": "[PICKUP_DATE]", "dropoff": "[DEPARTURE]"}


def question_slots(rfq: dict, values: dict, lang: str) -> str:
    """Optional prompt slots: only the answers this customer's mail needs."""
    if lang == "en":
        needed = [f"[{k}]" for k in ANSWER_SLOTS if values.get(k)]
        if needed:
            return ("They asked direct questions. Answer them by putting these sentences in, exactly as written: "
                    + " ".join(needed) + ".")
        return "They asked no extra question, so add no extra facts."
    topics = sorted(asked(str(rfq.get("customer_text") or "")))
    if not topics:
        return "They asked no extra question, so add no extra facts."
    hints = ", ".join(f"{t}: {TOPIC_SLOT[t]}" for t in topics)
    return f"They asked direct questions. Answer each in one short sentence using only these facts: {hints}."


def template(lang: str, values: dict) -> str:
    return fill(TEMPLATES.get(lang, TEMPLATES["en"]).format(agent=AGENT_NAME, company=COMPANY), values)


async def write_quote_email(rfq: dict, price: dict, http=None) -> Email:
    lang, values = facts(rfq, price)
    spoken = str(rfq.get("language") or lang)
    if spoken not in LANG_NAMES:
        spoken = lang
    native = spoken == lang
    if not native:
        depart = departure_date(as_date(price.get("ready_date")))
        values["ARRIVAL"] = short_day(quote_arrival(price), spoken)
        values["DEPARTURE"] = short_day(depart + timedelta(days=1), spoken)
        values["PICKUP_DATE"] = short_day(depart, spoken)
        values["VALID"] = valid_text(price, spoken) if price.get("valid_until") else short_day(date.today(), spoken)
        if spoken not in ("zh", "ja", "ko", "ar", "he", "th", "hi"):
            values["TOTAL"] = money(price["total"], price["currency"], spoken)
    subject = reply_subject(rfq.get("subject") or f"Air freight quote {rfq['origin']}-{rfq['destination']}")
    pref = preference(rfq.get("preference"))
    language = LANG_NAMES.get(spoken, "English")
    english = spoken == "en"
    prompt = PROMPT.format(
        language=language,
        greeting=GREETING.get(spoken, "Hi"),
        pref=pref,
        valid="HOLD" if english else "VALID",
        questions=question_slots(rfq, values, lang),
        snippet=snippet(rfq.get("customer_text", "")),
        signoff=values["SIGNOFF"] if english else SIGNOFF.get(spoken, "Cheers,"),
        agent=AGENT_NAME,
        company=COMPANY,
    )
    base = values
    if not english:
        prompt, values = native_slots(prompt, values, rfq, language, native)
    prompt = optional_slots(prompt, values)
    # A quote sent without any model call scores 0 cost points (rounds 7, 11 and 28 each lost
    # about 38), so a failed call is retried once. A failed call returns no text, so this is
    # still exactly one successful call per quote.
    reply = None
    for attempt in range(2):
        try:
            reply = await gateway.chat([{"role": "user", "content": prompt}], http=http)
            break
        except gateway.GatewayError as e:
            error = e
    if reply is None:
        return Email(subject, template(lang, base), used_llm=False, fallback_reason=str(error))

    tokens = {"in": reply.prompt_tokens, "out": reply.completion_tokens, "model": reply.model}
    draft = tidy(fix_greeting(reply.text.strip().strip("`").strip(), spoken))
    # Round 49: the model wrote "valid until [HOLD]", which reads "until for you today" and
    # threw the whole draft away. [HOLD] already carries its own preposition.
    # Round 56: "hold it at [HOLD]" read "hold it at for you today".
    draft = re.sub(r"\b(?:until|by|for|at|in|on|to|till)\s+(\[(?:HOLD|VALID)\])", r"\1", draft)
    issues = empty_inline(draft, values) + problems(draft, values, rfq.get("customer_text", ""))
    body = fill(draft, values)
    if not issues:
        issues = check_final(body, values, lang)
    if issues:
        body = template(lang, base)
    return Email(subject, body, used_llm=True, cost_usd=reply.cost_usd, fallback_reason="; ".join(issues) or None, tokens=tokens)
