import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import gateway
from .text import fresh_text, reply_subject

AGENT_NAME = os.getenv("AGENT_NAME") or "Lena"
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
LANG_NAMES = {"en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "pl": "Polish", "nl": "Dutch", "pt": "Portuguese"}


@dataclass
class Email:
    subject: str
    body: str
    used_llm: bool
    cost_usd: float = 0.0
    fallback_reason: str | None = None
    tokens: dict = field(default_factory=dict)


def money(amount: float, currency: str, lang: str) -> str:
    whole, cents = f"{float(amount):,.2f}".split(".")
    if lang == "en":
        return f"{currency} {whole},{cents}".replace(",", "X", whole.count(",")).replace("X", ",").replace(f"{whole},{cents}", f"{whole}.{cents}")
    sep = " " if lang == "fr" else "."
    return f"{whole.replace(',', sep)},{cents} {currency}"


def kg(v, lang) -> str:
    s = f"{float(v):,.1f}".rstrip("0").rstrip(".")
    return (s if lang == "en" else s.replace(",", "X").replace(".", ",").replace("X", ".")) + " kg"


def arrival_day(price: dict, lang: str, today: date | None = None) -> str:
    raw = price.get("arrival")
    if raw:
        d = datetime.fromisoformat(str(raw)[:10]).date()
    else:
        d = (today or date.today()) + timedelta(days=1 + int(price.get("transit_days") or 0))
    name = WEEKDAYS.get(lang, WEEKDAYS["en"]).split()[d.weekday()]
    return f"{name} {d.day:02d}.{d.month:02d}" if lang != "en" else f"{name} {d.strftime('%d %b')}"


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
    "en": {"freight": "air freight", "fuel": "fuel", "security": "security", "pickup": "door pickup", "awb": "AWB", "handling": "handling", "customs": "export customs"},
    "de": {"freight": "Luftfracht", "fuel": "Treibstoff", "security": "Sicherheit", "pickup": "Abholung", "awb": "AWB", "handling": "Handling", "customs": "Exportzoll"},
    "fr": {"freight": "fret aérien", "fuel": "carburant", "security": "sûreté", "pickup": "enlèvement", "awb": "LTA", "handling": "manutention", "customs": "douane export"},
    "es": {"freight": "flete aéreo", "fuel": "combustible", "security": "seguridad", "pickup": "recogida", "awb": "AWB", "handling": "handling", "customs": "aduana de exportación"},
    "it": {"freight": "nolo aereo", "fuel": "carburante", "security": "sicurezza", "pickup": "ritiro", "awb": "AWB", "handling": "handling", "customs": "dogana export"},
    "pl": {"freight": "fracht lotniczy", "fuel": "paliwo", "security": "ochrona", "pickup": "odbiór", "awb": "AWB", "handling": "obsługa", "customs": "odprawa eksportowa"},
}


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
        "ROUTE": f"{rfq['origin']} → {rfq['destination']}",
        "PIECES": f"{pieces} {unit[0] if pieces == 1 else unit[1]}",
        "GROSS": kg(rfq["gross_kg"], lang),
        "CHARGEABLE": kg(rfq["chargeable_kg"], lang),
        "CARRIER": price["carrier"],
        "TRANSIT": transit,
        "ARRIVAL": arrival_day(price, lang),
        "TOTAL": money(price["total"], price["currency"], lang),
        "INCLUDED": ", ".join(inc),
        "VALID": valid_text(price, lang),
    }
    return lang, values


TEMPLATES = {
    "en": """Hi [FIRST],

thanks for your request, our reference is [REF].
[ROUTE], [PIECES], [GROSS] gross, [CHARGEABLE] chargeable.
Best fit is [CARRIER]: [TRANSIT] transit, arriving around [ARRIVAL].
All-in price: [TOTAL].
That covers [INCLUDED].
The rate holds until [VALID]. Just reply yes and we'll book it.

Cheers,
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
Body is 5 to 8 short lines in two or three small paragraphs. First line is exactly "{greeting} [FIRST]," then a blank line. Never write the customer's name yourself, only [FIRST].
[PIECES] already includes its unit word, never add "pieces", "pallets" or similar after it. Write every word in {language}, including the words for gross and chargeable weight.
Use these placeholders exactly as written; never write any digit or price yourself:
[REF] [ROUTE] [PIECES] [GROSS] [CHARGEABLE] [CARRIER] [TRANSIT] [ARRIVAL] [TOTAL] [INCLUDED] [VALID]
Must contain, in your own words: thanks, and that our reference is [REF]; [ROUTE]; [PIECES], [GROSS] gross and [CHARGEABLE] chargeable; [CARRIER], [TRANSIT] and arrival [ARRIVAL]; one all-in price [TOTAL] (exactly once); what it includes: [INCLUDED]; valid until [VALID]; tell them to just reply yes and we'll book it.
One reply, one decision: give only this single routing and this single price. Never mention alternatives, other routings, other options, insurance, add-ons, or offering to check, compare or look into anything later. Never write the words "option", "alternatively" or "or".
The customer asked for the {pref} routing; you may say it is the {pref} one. Customer's message, for tone only:
---
{snippet}
---
End with exactly:
{signoff}
{agent}
{company}"""

GREETING = {"en": "Hi", "de": "Hallo", "fr": "Bonjour", "es": "Hola", "it": "Ciao", "pl": "Dzień dobry"}
SIGNOFF = {"en": "Cheers,", "de": "Viele Grüße", "fr": "Bien à vous,", "es": "Un saludo,", "it": "Un saluto,", "pl": "Pozdrawiam,"}


DASHES = re.compile(r"\s*[\u2014\u2013]\s*")
QUOTES = str.maketrans({"\u201c": '"', "\u201d": '"', "\u201e": '"', "\u00ab": '"', "\u00bb": '"',
                        "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u2026": "..."})


def tidy(text: str) -> str:
    text = text.translate(QUOTES)
    text = DASHES.sub(", ", text)
    return re.sub(r",\s*,", ",", text)


def fill(text: str, values: dict) -> str:
    for k, v in values.items():
        text = text.replace(f"[{k}]", v)
    unit = values.get("PIECES", "").split(" ", 1)[-1]
    if unit:
        extra = r"pieces?|pcs|pallets?|cartons?|boxes|crates?|kolli|stücke?|stk|paletten?|colis|palettes?|bultos|palés|colli|bancali|szt\.?|palet\w*"
        text = re.sub(rf"({re.escape(values['PIECES'])})(?:\s+(?:{re.escape(unit)}|{extra})\b\.?)+", r"\1", text, flags=re.I)
    text = tidy(re.sub(r" +,", ",", text))
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


GREET_LINE = re.compile(r"^\s*[^\n]{0,40}?,\s*$")


def fix_greeting(draft: str, lang: str) -> str:
    lines = draft.strip().splitlines()
    if lines and GREET_LINE.match(lines[0]):
        lines[0] = f"{GREETING.get(lang, 'Hi')} [FIRST],"
    else:
        lines = [f"{GREETING.get(lang, 'Hi')} [FIRST],", ""] + lines
    return "\n".join(lines)


def problems(draft: str, values: dict) -> list[str]:
    out = []
    if draft.count("[TOTAL]") != 1:
        out.append(f"[TOTAL] appears {draft.count('[TOTAL]')} times")
    if "[REF]" not in draft:
        out.append("no [REF]")
    bare = re.sub(r"\[[A-Z]+\]", "", draft)
    if re.search(r"\d", bare):
        out.append("model wrote digits")
    if re.search(r"\[[A-Za-z_ ]+\]", bare):
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
    return out


ALTERNATIVES = {
    "all": r"alternativ|\boptions?\b|\bor we can\b|\binsurance\b|\bcheaper\b|\bfaster\b|\banother (routing|carrier|quote|offer)\b|\b(check|look into|compare)\b",
    "en": r"\bor\b",
    "de": r"\boder\b|versicherung|günstiger|schneller|\bandere[nsr]? (option|route|möglichkeit|angebot)|\bmöglichkeit",
    "fr": r"\bou\b|assurance|moins cher|plus rapide|\bautre (option|solution|offre)|\bsolution",
    "es": r"\bo\b|opci[oó]n|seguro\b|más barat|más rápid|\botra (ruta|oferta)",
    "it": r"\bo\b|\boppure\b|opzion|assicura|più economic|più velo|\baltra (rotta|offerta)",
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
    alt = alternatives(body.replace(values.get("CARRIER", ""), ""), lang)
    if alt:
        out.append(f"offers an alternative: {sorted(set(a.lower() for a in alt))}")
    return out


def snippet(text: str, limit=500) -> str:
    t = re.sub(r"\s+", " ", fresh_text(text or "")).strip()
    return t[:limit]


def template(lang: str, values: dict) -> str:
    return fill(TEMPLATES.get(lang, TEMPLATES["en"]).format(agent=AGENT_NAME, company=COMPANY), values)


async def write_quote_email(rfq: dict, price: dict, http=None) -> Email:
    lang, values = facts(rfq, price)
    subject = reply_subject(rfq.get("subject") or f"Air freight quote {rfq['origin']}-{rfq['destination']}")
    pref = preference(rfq.get("preference"))
    prompt = PROMPT.format(
        language=LANG_NAMES.get(lang, "English"),
        greeting=GREETING.get(lang, "Hi"),
        pref=pref,
        snippet=snippet(rfq.get("customer_text", "")),
        signoff=SIGNOFF.get(lang, "Cheers,"),
        agent=AGENT_NAME,
        company=COMPANY,
    )
    try:
        reply = await gateway.chat([{"role": "user", "content": prompt}], http=http)
    except gateway.GatewayError as e:
        return Email(subject, template(lang, values), used_llm=False, fallback_reason=str(e))

    tokens = {"in": reply.prompt_tokens, "out": reply.completion_tokens, "model": reply.model}
    draft = fix_greeting(reply.text.strip().strip("`").strip(), lang)
    issues = problems(draft, values)
    body = fill(draft, values)
    if not issues:
        issues = check_final(body, values, lang)
    if issues:
        body = template(lang, values)
    return Email(subject, body, used_llm=True, cost_usd=reply.cost_usd, fallback_reason="; ".join(issues) or None, tokens=tokens)
