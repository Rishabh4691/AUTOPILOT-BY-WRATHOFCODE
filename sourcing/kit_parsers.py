"""Parsers for the airline rate sheets (start kit + monthly updates).

The 10 sheets come in 7 file types (xlsx, pdf, docx, txt, scanned jpg) and
5 layouts, but they all say the same things. So every file is first turned
into plain text lines, and ONE line parser reads all layouts:

  table, lane per row   "CGN-SYD  5  EUR 75.00  EUR 5.92 ..."      (Yellowtail, Quetzal, Danube)
                        "CGN Cologne > DEL Delhi  2 days  87.98 ..." (Wayzata)
                        "Cologne (CGN) to Lagos (LOS)  D+4  EUR 76.00 ..." (Helix)
  sections per origin   "Origin: CGN" then "LOS  5  108,00 ..."     (Elbflug, Kestrel, Vega)
  block per lane        "CGN-MIA" then "Transit 2 days", "Minimum 78,00",
                        "from 0 kg 2,91", ..., "Fuel 0.70"          (Orion, Cobalt)
  surcharges            "CGN-LOS: fuel 1,21 per kg, security 0,10 per kg",
                        a Fuel/Security table, or Fuel/Security columns.

Breaks: "-45" / "from 0 kg" / "0 kg+" are the N rate (from 0 kg).
Any row it can't read completely becomes a problem (an alarm), never a guess.
"""

from __future__ import annotations

import io
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .ingest import register
from .models import Break, Surcharge, Tariff, TariffLane
from .weights import D

MONTHS = {
    m: i
    for i, m in enumerate(
        "january february march april may june july august september october november december".split(),
        1,
    )
}


class TariffParseError(Exception):
    def __init__(self, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.problems = problems or []


# ------------------------------------------------------------ text extraction
def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return repr(v)
    return str(v).strip()


def xlsx_lines(content: bytes) -> list[str]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    lines = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [_cell(v) for v in row]
            if any(cells):
                lines.append("  ".join(c for c in cells if c))
    return lines


def xls_lines(content: bytes) -> list[str]:
    import pandas as pd

    lines = []
    for _, df in pd.read_excel(io.BytesIO(content), sheet_name=None, header=None).items():
        for row in df.itertuples(index=False):
            cells = [_cell(None if (isinstance(v, float) and v != v) else v) for v in row]
            if any(cells):
                lines.append("  ".join(c for c in cells if c))
    return lines


def pdf_lines(content: bytes) -> list[str]:
    try:  # poppler keeps columns best; fall back to pdfplumber (pip only)
        out = subprocess.run(
            ["pdftotext", "-layout", "-", "-"], input=content, capture_output=True, timeout=30
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.decode("utf-8", "replace").splitlines()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    import pdfplumber

    lines: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            lines += (page.extract_text() or "").splitlines()
    return lines


def docx_lines(content: bytes) -> list[str]:
    from xml.etree import ElementTree as ET
    import zipfile

    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(content)).read("word/document.xml"))
    lines = []
    for el in root.find(f"{w}body"):
        if el.tag == f"{w}p":
            t = "".join(n.text or "" for n in el.iter(f"{w}t"))
            if t.strip():
                lines.append(t)
        elif el.tag == f"{w}tbl":
            for tr in el.iter(f"{w}tr"):
                cells = ["".join(n.text or "" for n in tc.iter(f"{w}t")) for tc in tr.findall(f"{w}tc")]
                lines.append("  ".join(c for c in cells if c.strip()))
    return lines


def image_lines(content: bytes) -> list[str]:
    """OCR. Scans misread digits now and then, so rows that don't add up are rejected."""
    import pytesseract
    from PIL import Image

    text = pytesseract.image_to_string(Image.open(io.BytesIO(content)), config="--psm 6")
    return text.splitlines()


def text_lines(filename: str, content: bytes) -> list[str]:
    ext = Path(filename).suffix.lower()
    if ext == ".xlsx":
        return xlsx_lines(content)
    if ext == ".xls":
        return xls_lines(content)
    if ext == ".pdf":
        return pdf_lines(content)
    if ext == ".docx":
        return docx_lines(content)
    if ext in (".jpg", ".jpeg", ".png"):
        return image_lines(content)
    return content.decode("utf-8", "replace").splitlines()


# ---------------------------------------------------------------- the parser
def num(text: str) -> Decimal:
    t = text.strip().replace("EUR", "").replace("€", "").strip()
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    else:
        t = t.replace(",", ".")
    return D(t)


def parse_date(text: str) -> date | None:
    t = text.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(t[:10], fmt).date()
        except ValueError:
            pass
    m = re.match(r"(\d{1,2})\.?\s+([A-Za-z]+)\s+(\d{4})", t)
    if m and m.group(2).lower() in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    return None


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_CLEAN_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
# Plausibility limits (kit max: rate 6.53, minimum 144.16, fuel 1.43, security 0.27).
# A dropped comma ("1,22" read as "122") lands far outside them.
MAX_RATE, MAX_MINIMUM, MAX_SURCHARGE = D("50"), D("2000"), D("20")
_LANE_PATTERNS = [
    re.compile(r"^([A-Z]{3})\s*-\s*([A-Z]{3})\b"),  # CGN-SYD
    re.compile(r"^([A-Z]{3})\s+[A-Za-z .'()-]*?>\s*([A-Z]{3})\b[A-Za-z .'-]*"),  # CGN Cologne > DEL Delhi
    re.compile(r"^[^()\d]*\(([A-Z]{3})\)\s*to\s*[^()\d]*\(([A-Z]{3})\)"),  # Cologne (CGN) to Lagos (LOS)
]
_DEST_PATTERNS = [
    re.compile(r"^([A-Z]{3})\b(?!\s*[->])"),  # LOS (under "Origin: CGN")
    re.compile(r"^[A-Za-z][A-Za-z .'-]*\(([A-Z]{3})\)"),  # Lagos (LOS)
]
_ORIGIN = re.compile(r"^Origin:\s*(?:[^()]*\()?([A-Z]{3})\)?")
_SURCHARGE_LINE = re.compile(
    r"^(?P<lane>.+?):\s*fuel\s+(?:EUR\s*)?(?P<fuel>\d+(?:[.,]\d+)?)\s*per\s*kg,?\s*"
    r"security\s+(?:EUR\s*)?(?P<sec>\d+(?:[.,]\d+)?)",
    re.I,
)
_BREAK_HEADER = re.compile(r"(?:^|\s)(?:[-+]45\b|from\s*45\s*kg|45\s*kg\+)", re.I)
_BREAK_LABEL = re.compile(
    r"from\s*(\d+)\s*kg|(\d+)\s*kg\s*\+|(?<![\w.,])([-+])(\d+)(?![\w.,])", re.I
)
_TRANSIT = re.compile(r"^\s*(?:D\s*\+\s*(\d+)|(\d+)\s*days?\b|(\d+)(?![.,]\d))", re.I)
_BLOCK_KV = re.compile(
    r"^(transit|minimum|fuel|security|from\s*(\d+)\s*kg)\s*:?\s+(.+)$", re.I
)


def _match_lane(line: str, origin: str | None):
    for pat in _LANE_PATTERNS:
        if m := pat.match(line):
            return m.group(1), m.group(2), line[m.end():]
    if origin:
        for pat in _DEST_PATTERNS:
            if m := pat.match(line):
                return origin, m.group(1), line[m.end():]
    return None


def _breaks_from_header(line: str) -> list[Decimal]:
    out = []
    for m in _BREAK_LABEL.finditer(line):
        if m.group(1) is not None:
            out.append(D(m.group(1)))
        elif m.group(2) is not None:
            out.append(D(m.group(2)))
        else:
            out.append(Decimal("0") if m.group(3) == "-" else D(m.group(4)))
    return out


@dataclass
class _Lane:
    origin: str
    destination: str
    transit: int | None = None
    minimum: Decimal | None = None
    rates: dict = field(default_factory=dict)  # from_kg -> rate
    fuel: Decimal | None = None
    security: Decimal | None = None


def parse_tariff_lines(lines: list[str], source: str = "") -> tuple[Tariff, list[str]]:
    """(tariff, problems). Problems mean some rows could not be read."""
    airline = None
    currency = None
    valid_from = valid_to = None
    kg_per_cbm: Decimal | None = None
    surcharge_weight = "billed"
    breaks: list[Decimal] = []
    inline_sc = False
    origin: str | None = None
    in_surcharges = False
    lanes: dict[tuple[str, str], _Lane] = {}
    order: list[tuple[str, str]] = []
    block: _Lane | None = None
    problems: list[str] = []
    surcharge_rows: dict[tuple[str, str], tuple[Decimal, Decimal]] = {}

    def lane(o: str, d: str) -> _Lane:
        key = (o, d)
        if key not in lanes:
            lanes[key] = _Lane(o, d)
            order.append(key)
        return lanes[key]

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        low = line.lower()

        # ------------------------------------------------ header and rules
        if airline is None and "|" in line:
            airline = line.split("|")[0].strip()
            continue
        if m := re.match(r"^Currency\s*:?\s+([A-Z]{3})\b", line):
            currency = m.group(1)
            continue
        if m := re.match(r"^Valid from\s*:?\s+(.+)$", line, re.I):
            valid_from = parse_date(m.group(1))
            continue
        if m := re.match(r"^Valid (?:to|until)\s*:?\s+(.+)$", line, re.I):
            valid_to = parse_date(m.group(1))
            continue
        if m := re.search(r"1\s*cbm\s*=\s*(\d+(?:[.,]\d+)?)\s*kg", line, re.I):
            kg_per_cbm = num(m.group(1))
        if "surcharge" in low and "per kg" in low and not low.startswith("surcharges per kg"):
            if "billed" in low:
                surcharge_weight = "billed"
            elif "chargeable" in low:
                surcharge_weight = "chargeable"
        if low.startswith(("all rates", "chargeable weight", "fuel and security", "the minimum")):
            continue

        # ------------------------------------------------ surcharges
        if m := _SURCHARGE_LINE.match(line):
            hit = _match_lane(m.group("lane").strip(), None)
            if hit:
                surcharge_rows[(hit[0], hit[1])] = (num(m.group("fuel")), num(m.group("sec")))
            else:
                problems.append(f"surcharge line without a lane: {line}")
            continue
        if low.startswith("surcharges per kg") or low.startswith("surcharges"):
            in_surcharges = True
            block = None
            continue

        # ------------------------------------------------ sections and headers
        if m := _ORIGIN.match(line):
            origin = m.group(1)
            block = None
            continue
        # ------------------------------------------------ block key/values
        # (before the header check: "from 45 kg 4.17" is a value, not a header)
        if block is not None and (m := _BLOCK_KV.match(line)):
            key, value = m.group(1).lower(), m.group(3)
            try:
                if key == "transit":
                    t = _TRANSIT.match(value)
                    block.transit = int(next(g for g in t.groups() if g)) if t else None
                elif key == "minimum":
                    block.minimum = num(value)
                elif key == "fuel":
                    block.fuel = num(value)
                elif key == "security":
                    block.security = num(value)
                else:
                    block.rates[D(m.group(2))] = num(value)
            except Exception:
                problems.append(f"{block.origin}-{block.destination}: can't read '{line}'")
            continue
        if _BREAK_HEADER.search(line) and len(_breaks_from_header(line)) >= 3:
            breaks = _breaks_from_header(line)
            inline_sc = "fuel" in low and "security" in low
            continue

        # ------------------------------------------------ lane rows
        hit = _match_lane(line, origin)
        if not hit:
            continue
        o, d, rest = hit
        nums_text = rest
        if in_surcharges:
            tokens = nums_text.replace("EUR", " ").replace("€", " ").split()
            if len(tokens) == 2 and all(_CLEAN_NUMBER.fullmatch(tok) for tok in tokens):
                surcharge_rows[(o, d)] = (num(tokens[0]), num(tokens[1]))
            else:
                problems.append(f"surcharge row {o}-{d}: expected 2 clean numbers in '{line}'")
            continue
        if not _NUMBER.search(rest):
            block = lane(o, d)  # block layout: values follow on the next lines
            continue
        block = None
        t = _TRANSIT.match(rest)
        transit = None
        if t:
            transit = int(next(g for g in t.groups() if g))
            rest = rest[t.end():]
        tokens = rest.replace("EUR", " ").replace("€", " ").split()
        junk = [tok for tok in tokens if not _CLEAN_NUMBER.fullmatch(tok)]
        if junk:  # OCR noise like "57;" or "a2)" -> never guess a price
            problems.append(f"{o}-{d}: unreadable cells {junk} in '{line}'")
            continue
        values = [num(tok) for tok in tokens]
        n = len(breaks)
        if not n:
            problems.append(f"{o}-{d}: row before any weight-break header")
            continue
        if len(values) == n + 1 or (inline_sc and len(values) == n + 3):
            ln = lane(o, d)
            ln.transit = transit
            ln.minimum = values[0]
            ln.rates = dict(zip(breaks, values[1 : n + 1]))
            if len(values) == n + 3:
                ln.fuel, ln.security = values[n + 1], values[n + 2]
        else:
            problems.append(
                f"{o}-{d}: expected {n + 1}{' or ' + str(n + 3) if inline_sc else ''} numbers, "
                f"got {len(values)} in '{line}'"
            )

    # ------------------------------------------------ assemble
    if airline is None:
        raise TariffParseError(f"{source}: no 'Airline | Air export tariff' title line")
    if currency is None:
        problems.append("no currency line")
    tl: list[TariffLane] = []
    for key in order:
        ln = lanes[key]
        if key in surcharge_rows:
            ln.fuel, ln.security = surcharge_rows[key]
        where = f"{ln.origin}-{ln.destination}"
        if ln.minimum is None or not ln.rates:
            problems.append(f"{where}: missing minimum or rates")
            continue
        if ln.fuel is None or ln.security is None:
            problems.append(f"{where}: no fuel/security surcharge found")
            continue
        r = [ln.rates[k] for k in sorted(ln.rates)]
        if any(b > a for a, b in zip(r, r[1:])):
            problems.append(f"{where}: a rate goes UP with weight {r} (misread?)")
            continue
        if max(r) > MAX_RATE or ln.minimum > MAX_MINIMUM or max(ln.fuel, ln.security) > MAX_SURCHARGE:
            problems.append(f"{where}: value out of range (rate/minimum/surcharge) - misread?")
            continue
        tl.append(
            TariffLane(
                origin=ln.origin,
                destination=ln.destination,
                transit_days=ln.transit,
                min_charge=ln.minimum,
                breaks=[Break(from_kg=k, rate_per_kg=v) for k, v in sorted(ln.rates.items())],
                surcharges=[
                    Surcharge(code="FSC", name="Fuel surcharge", basis="per_kg", amount=ln.fuel),
                    Surcharge(code="SSC", name="Security surcharge", basis="per_kg", amount=ln.security),
                ],
            )
        )
    for key in surcharge_rows:
        if key not in lanes:
            problems.append(f"surcharges for {key[0]}-{key[1]} but no rate row")

    code = slug(airline)
    tariff = Tariff(
        tariff_id=f"{code}-{valid_from:%Y-%m}" if valid_from else code,
        airline_code=code,
        airline=airline,
        currency=currency or "EUR",
        valid_from=valid_from,
        valid_to=valid_to,
        lanes=tl,
        kg_per_cbm=kg_per_cbm,
        surcharge_weight=surcharge_weight,
        source_file=source or None,
    )
    return tariff, problems


def parse_file(filename: str, content: bytes) -> tuple[Tariff, list[str]]:
    return parse_tariff_lines(text_lines(filename, content), Path(filename).name)


# Monthly tariffs by mail go through the same parser (see ingest.py).
_SHEET_EXT = (".xlsx", ".xls", ".pdf", ".docx", ".txt", ".jpg", ".jpeg", ".png")


@register("rate-sheet", lambda fn, data, code: fn.lower().endswith(_SHEET_EXT))
def _parse_for_ingest(filename: str, content: bytes, airline_code: str | None) -> list[Tariff]:
    tariff, problems = parse_file(filename, content)
    if problems:
        raise TariffParseError(f"{filename}: {len(problems)} rows unreadable", problems)
    return [tariff]
