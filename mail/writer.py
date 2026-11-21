import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import gateway, store
from .client import reply_subject

AGENT_NAME = os.getenv("AGENT_NAME") or "Lena"
COMPANY = "WRATHOFCODE Air Freight"

SLOTS = ("FIRST", "REF", "ROUTE", "PIECES", "GROSS", "CHARGEABLE", "CARRIER", "TRANSIT", "ARRIVAL", "TOTAL", "INCLUDED", "VALID")
MONEY = re.compile(r"(?:(?:EUR|USD|GBP|CHF|PLN|€|\$|£)\s?\d[\d.,\s]*\d|\d[\d.,\s]*\d?\s?(?:EUR|USD|GBP|CHF|PLN|€|\$|£))")
STIFF = re.compile(
    r"dear sir|madam|we are pleased|i hope this (e-?mail|message|finds)|do not hesitate|please find below|kindly|"
    r"sehr geehrte|wir freuen uns, ihnen|madame, monsieur|nous avons le plaisir|estimad[oa]s? señor|egregi|"
    r"as an ai|language model",
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
    return {"de": "heute", "fr": "aujourd'hui", "es": "hoy", "it": "oggi", "pl": "dziś"}.get(lang, "today")


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
Happy to check another routing if timing or budget changes.

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
Wenn sich Termin oder Budget ändern, schaue ich gern nach einer anderen Option.

Viele Grüße
{agent}
{company}""",
    "fr": """Bonjour [FIRST],

merci pour votre demande, notre référence est [REF].
[ROUTE], [PIECES], [GROSS] brut, [CHARGEABLE] taxable.
La meilleure option est [CARRIER] : [TRANSIT] de transit, arrivée vers [ARRIVAL].
Prix tout compris : [TOTAL].
Cela inclut [INCLUDED].
Le tarif est valable jusqu'au [VALID]. Répondez simplement oui et nous réservons.
Si le délai ou le budget change, je regarde volontiers une autre option.

Bien à vous,
{agent}
{company}""",
    "es": """Hola [FIRST],

gracias por tu solicitud, nuestra referencia es [REF].
[ROUTE], [PIECES], [GROSS] brutos, [CHARGEABLE] tasables.
La mejor opción es [CARRIER]: [TRANSIT] de tránsito, llegada sobre el [ARRIVAL].
Precio todo incluido: [TOTAL].
Incluye [INCLUDED].
La tarifa vale hasta el [VALID]. Responde sí y lo reservamos.
Si cambian los plazos o el presupuesto, miro encantada otra opción.

Un saludo,
{agent}
{company}""",
    "it": """Ciao [FIRST],

grazie per la richiesta, il nostro riferimento è [REF].
[ROUTE], [PIECES], [GROSS] lordi, [CHARGEABLE] tassabili.
L'opzione migliore è [CARRIER]: [TRANSIT] di transito, arrivo verso [ARRIVAL].
Prezzo tutto incluso: [TOTAL].
Comprende [INCLUDED].
La tariffa vale fino al [VALID]. Rispondi sì e prenotiamo.
Se cambiano tempi o budget, controllo volentieri un'altra opzione.

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
Jeśli zmieni się termin lub budżet, chętnie sprawdzę inną opcję.

Pozdrawiam,
{agent}
{company}""",
}

PROMPT = """You write one reply email for an air freight forwarder. Write it in {language}.
Voice: a friendly, experienced human freight agent writing quickly between calls. Warm, direct, modern. Use contractions where natural.
Never use: "Dear Sir or Madam", "We are pleased to inform you", "I hope this finds you well", "do not hesitate", "kindly", emojis, bullet points, markdown.
Body is 6 to 10 short lines. Greet with "{greeting} [FIRST]," on the first line, then a blank line. [PIECES] already includes its unit word.
Use these placeholders exactly as written; never write any digit or price yourself:
[REF] [ROUTE] [PIECES] [GROSS] [CHARGEABLE] [CARRIER] [TRANSIT] [ARRIVAL] [TOTAL] [INCLUDED] [VALID]
Must contain, in your own words: thanks, and that our reference is [REF]; [ROUTE]; [PIECES], [GROSS] gross and [CHARGEABLE] chargeable; [CARRIER], [TRANSIT] and arrival [ARRIVAL]; one all-in price [TOTAL] (exactly once); what it includes: [INCLUDED]; valid until [VALID]; tell them to just reply yes and we'll book it; one light line offering to check a {other} option, with no price.
This is the {pref} option. Customer's message, for tone only:
---
{snippet}
---
End with exactly:
{signoff}
{agent}
{company}"""

GREETING = {"en": "Hi", "de": "Hallo", "fr": "Bonjour", "es": "Hola", "it": "Ciao", "pl": "Dzień dobry"}
SIGNOFF = {"en": "Cheers,", "de": "Viele Grüße", "fr": "Bien à vous,", "es": "Un saludo,", "it": "Un saluto,", "pl": "Pozdrawiam,"}


def fill(text: str, values: dict) -> str:
    for k, v in values.items():
        text = text.replace(f"[{k}]", v)
    return re.sub(r" +,", ",", text)


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
    if not 6 <= len(lines) <= 16:
        out.append(f"{len(lines)} lines")
    return out


def check_final(body: str, values: dict) -> list[str]:
    totals = MONEY.findall(body)
    if len(totals) != 1 or values["TOTAL"] not in body:
        return [f"expected exactly one total, found {totals}"]
    return []


def snippet(text: str, limit=500) -> str:
    from .router import fresh_text

    t = re.sub(r"\s+", " ", fresh_text(text or "")).strip()
    return t[:limit]


def template(lang: str, values: dict) -> str:
    return fill(TEMPLATES.get(lang, TEMPLATES["en"]).format(agent=AGENT_NAME, company=COMPANY), values)


async def write_quote_email(rfq: dict, price: dict, http=None) -> Email:
    lang, values = facts(rfq, price)
    subject = reply_subject(rfq.get("subject") or f"Air freight quote {rfq['origin']}-{rfq['destination']}")
    pref = (rfq.get("preference") or price.get("option") or "cheapest").lower()
    prompt = PROMPT.format(
        language=LANG_NAMES.get(lang, "English"),
        greeting=GREETING.get(lang, "Hi"),
        other="faster" if pref.startswith("cheap") else "cheaper",
        pref=pref,
        snippet=snippet(rfq.get("customer_text", "")),
        signoff=SIGNOFF.get(lang, "Cheers,"),
        agent=AGENT_NAME,
        company=COMPANY,
    )
    t0 = time.monotonic()
    try:
        reply = await gateway.chat([{"role": "user", "content": prompt}], http=http)
    except gateway.GatewayError as e:
        store.log_event("rfq", rfq.get("id"), "write", "fail", f"Gateway down, template used: {e}"[:300], (time.monotonic() - t0) * 1000)
        return Email(subject, template(lang, values), used_llm=False, fallback_reason=str(e))

    tokens = {"in": reply.prompt_tokens, "out": reply.completion_tokens, "model": reply.model}
    draft = reply.text.strip().strip("`").strip()
    issues = problems(draft, values)
    body = fill(draft, values)
    if not issues:
        issues = check_final(body, values)
    if issues:
        body = template(lang, values)
    store.log_event(
        "rfq",
        rfq.get("id"),
        "write",
        "ok",
        "Email written by LLM" if not issues else f"LLM draft rejected ({'; '.join(issues)}), template used",
        reply.ms,
        reply.cost_usd,
        data={**tokens, "fallback": bool(issues)},
    )
    return Email(subject, body, used_llm=True, cost_usd=reply.cost_usd, fallback_reason="; ".join(issues) or None, tokens=tokens)
