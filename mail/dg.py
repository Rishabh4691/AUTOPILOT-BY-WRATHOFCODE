import io
import re
import zipfile
from dataclasses import dataclass, field

UN = re.compile(r"\bUN\s?-?(\d{4})\b", re.I)
CLASS = re.compile(r"\b(?:hazard |dg |dangerous goods )?class\s*([1-9](?:\.\d)?)\b", re.I)
DG_FIELD = re.compile(
    r"(dangerous goods|hazardous|gefahrgut|marchandises dangereuses|mercanc[ií]as peligrosas|merci pericolose|"
    r"towary niebezpieczne|imdg|iata dgr|adr)\s*[:=]\s*(?P<v>[^\n;]{1,80})",
    re.I,
)
NEGATIVE = re.compile(r"^\s*(no|none|n/?a|nein|non|keine?|not applicable|-|0)\b", re.I)
DG_GOODS = re.compile(
    r"\b(adhesives?|glues?|klebstoff\w*|paints?|lacquers?|lacke?|varnish\w*|solvents?|lösungsmittel|thinners?|"
    r"a[eé]ro[sz]ol\w*|spray ?cans?|spraydosen?|sprühdosen?|bombolett\w*|bombes? a[eé]rosol\w*|"
    r"adh[eé]si(?:f|fs|vos?)|adesiv[io]|colla|klej\w*|pegamentos?|batterie al litio|bater[ií]as? de litio|litowo\w*|"
    r"perfumes?|fragrances?|parfum\w*|lithium[- ]ion|lithium batter\w*|li-?ion|"
    r"flammable|entzündlich|inflammable|corrosive|ätzend|resins?|harze?|printing inks?|druckfarben?|"
    r"kraftstoff|petrol|gasoline|diesel fuel|ethanol|isopropanol|compressed gas|gas cylinders?|"
    r"dry ice|trockeneis|safety matches|fireworks|pesticides?|explosives?|oxidi[sz]ers?|peroxides?)\b",
    re.I,
)
DOCS = re.compile(
    r"(?<![a-z])(shipper'?s declaration|dgd|dangerous goods declaration|msds|sds|safety data sheet|"
    r"sicherheitsdatenblatt|fiche de (données de )?sécurité|ficha de (datos de )?seguridad|scheda (dati )?di sicurezza)(?![a-z])",
    re.I,
)


NEGATED = re.compile(
    r"(?:\b(?:no|not|non|without|free of|kein\w*|nicht|ohne|sans|pas de|sin|senza|bez)\b[^.;,!?\n]{0,25}|\bnon-?)$",
    re.I,
)
DG_CONTEXT = re.compile(r"dangerous|hazard|\bDG\b|gefahrgut|flammable|entzündlich|\bUN\s?\d{4}", re.I)


def dg_goods(text: str):
    """First goods keyword that is not negated ("non-flammable", "no lithium batteries")."""
    for m in DG_GOODS.finditer(text or ""):
        if not NEGATED.search(text[max(0, m.start() - 40) : m.start()]):
            return m
    return None


def body_classes(text: str) -> list[str]:
    """Hazard classes written in the mail itself, e.g. "Class 3 dangerous goods"."""
    out = []
    for line in (text or "").splitlines():
        for m in CLASS.finditer(line):
            if DG_CONTEXT.search(line) and not NEGATED.search(line[max(0, m.start() - 40) : m.start()]):
                out.append(m.group(1))
    return out


@dataclass
class DgCheck:
    dangerous: bool
    reasons: list[str] = field(default_factory=list)
    un_numbers: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    docs_attached: bool = False


def xlsx_text(data: bytes) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                lines.append(": ".join(cells) if len(cells) == 2 else " | ".join(cells))
    return "\n".join(lines)


def docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages[:10])


def image_text(data: bytes) -> str:
    import pytesseract
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        return pytesseract.image_to_string(img.convert("L"))


SPECIAL = re.compile(
    r"\b(perishables?|fresh (fish|fruit|flowers|meat)|frozen|chilled|temperature[- ]controlled|cool chain|"
    r"\+2 ?(°|to) ?\+?8|pharma\w*|vaccines?|live animals?|lebende tiere|valuables?|gold|jewel\w*|banknotes?|"
    r"human remains|diplomatic|weapons?|ammunition|munitions?|drones? with batter\w*|kühlware|tiefgekühlt)\b",
    re.I,
)


def special_cargo(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in SPECIAL.finditer(text or "")})


def attachment_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    try:
        if name.endswith((".png", ".jpg", ".jpeg")):
            return image_text(data)
        if name.endswith((".xlsx", ".xlsm")):
            return xlsx_text(data)
        if name.endswith(".docx"):
            return docx_text(data)
        if name.endswith(".pdf"):
            return pdf_text(data)
        if name.endswith((".csv", ".txt", ".tsv")):
            return data.decode("utf-8", "ignore")
    except Exception:
        return ""
    return ""


def check(body: str, attachments: list[tuple[str, str]]) -> DgCheck:
    sources = [("mail", body)] + [(name, text) for name, text in attachments]
    reasons, uns, classes = [], [], []
    docs = any(DOCS.search(name) for name, _ in attachments)
    for where, text in sources:
        for m in UN.finditer(text):
            uns.append(m.group(1))
            reasons.append(f"UN{m.group(1)} in {where}")
        for m in DG_FIELD.finditer(text):
            value = m.group("v").strip()
            if not NEGATIVE.match(value):
                reasons.append(f"'{m.group(1)}: {value[:40]}' in {where}")
                classes += CLASS.findall(value)
        if where != "mail":
            classes += CLASS.findall(text)
            if DOCS.search(text[:400]):
                docs = True
        else:
            for c in body_classes(text):
                classes.append(c)
                reasons.append(f"class {c} in {where}")
    goods = dg_goods(body) or next((dg_goods(t) for _, t in attachments if dg_goods(t)), None)
    if goods and not reasons:
        reasons.append(f"'{goods.group(0)}' is usually dangerous goods")
    return DgCheck(
        dangerous=bool(reasons),
        reasons=reasons,
        un_numbers=sorted(set(uns)),
        classes=sorted(set(classes)),
        docs_attached=docs,
    )


DOCS_REQUEST = {
    "en": (
        "Hi {first},\n\nthanks for the details, reference {ref}. Before I price this: {why} "
        "That makes it dangerous goods for air freight, so I need the paperwork first.\n\n"
        "Could you send the Shipper's Declaration for Dangerous Goods and the safety data sheet (MSDS/SDS), "
        "with UN number, proper shipping name, class, packing group and net quantity per package?\n\n"
        "As soon as I have them I'll come back with one all-in price.\n\nCheers,\n{agent}\n{company}"
    ),
    "de": (
        "Hallo {first},\n\ndanke für die Angaben, Referenz {ref}. Bevor ich das kalkuliere: {why} "
        "Damit ist es Gefahrgut in der Luftfracht, ich brauche also zuerst die Unterlagen.\n\n"
        "Können Sie mir die Gefahrgutanmeldung (Shipper's Declaration for Dangerous Goods) und das "
        "Sicherheitsdatenblatt schicken, mit UN-Nummer, richtiger Versandbezeichnung, Klasse, "
        "Verpackungsgruppe und Nettomenge pro Packstück?\n\n"
        "Sobald ich sie habe, melde ich mich mit einem All-in-Preis.\n\nViele Grüße\n{agent}\n{company}"
    ),
}


def why_text(result: DgCheck, lang: str) -> str:
    un = ", ".join(f"UN{u}" for u in result.un_numbers)
    cls = ", ".join(result.classes)
    if lang == "de":
        if un:
            return f"Laut Packliste ist die Ware {un}{f', Klasse {cls}' if cls else ''}."
        return "Die Ware gilt in der Luftfracht normalerweise als Gefahrgut."
    if un:
        return f"your packing list shows {un}{f', class {cls}' if cls else ''}."
    return "goods like these normally travel as dangerous goods."


def docs_request(result: DgCheck, lang: str, first: str, ref: str, agent: str, company: str) -> str:
    lang = lang if lang in DOCS_REQUEST else "en"
    body = DOCS_REQUEST[lang].format(
        first=first or ("there" if lang == "en" else ""),
        ref=ref,
        why=why_text(result, lang),
        agent=agent,
        company=company,
    )
    return re.sub(r" +,", ",", body)
