"""Read quote requests sent as structured data (JSON, XML, CSV, "a | b" tables).

The rules extractor reads prose and "Key: value" lines. A request written as JSON
({"origin": "FRA", "gross_weight_kg": 850}), XML (<Origin>FRA</Origin>), a two-column CSV or a
pipe table was not read at all (no origin, no weight). This turns such data into plain
"Origin: FRA / Gross weight: 850 kg" lines that are appended to the original text, so nothing is
lost. Values are only copied, never interpreted as instructions.
"""

from __future__ import annotations

import csv
import io
import json
import re

FIELDS = (
    # (pattern on the normalised key, line template)
    (re.compile(r"^(origin|from|departure|origin airport|airport of departure)$"), "Origin: {v}"),
    (re.compile(r"^(destination|to|dest|destination airport|airport of destination)$"), "Destination: {v}"),
    (re.compile(r"(^|\b)(pieces|pcs|packages|colli|number of pieces|qty|quantity)(\b|$)"), "Total pieces: {v}"),
    (re.compile(r"(gross)|(^weight)|(weight kg)|(^kg$)"), "Gross weight: {v} {unit}"),
    (re.compile(r"(volume)|(^cbm$)|(^m3$)"), "Total volume: {v} cbm"),
    (re.compile(r"(service|preference|priority|mode)$"), "Service: {v}"),
    (re.compile(r"(ready|pickup date|cargo ready)"), "Ready date: {v}"),
)
MAX_LINES = 60


def _key(raw: str) -> str:
    key = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(raw))
    return re.sub(r"[_\-]+", " ", key).strip().lower()


def _unit(key: str, unit: str | None) -> str:
    text = f"{key} {unit or ''}".lower()
    return "lb" if re.search(r"\blbs?\b|pound", text) else "kg"


def _lines(pairs: list[tuple[str, str, str | None]]) -> list[str]:
    out: list[str] = []
    for raw_key, value, unit in pairs[:MAX_LINES]:
        value = str(value).strip()
        if not value or len(value) > 200:
            continue
        key = _key(raw_key)
        for pattern, template in FIELDS:
            if pattern.search(key):
                out.append(template.format(v=value, unit=_unit(key, unit)))
                break
        # Unknown keys are skipped: the original text is still read as usual, and an HTML mail's
        # <p>/<td> tags must not add a second copy of its weights.
    return out


def _flatten(data, prefix: str = "") -> list[tuple[str, str, str | None]]:
    pairs: list[tuple[str, str, str | None]] = []
    if isinstance(data, dict):
        for k, v in data.items():
            pairs += _flatten(v, str(k))
    elif isinstance(data, list):
        for item in data[:MAX_LINES]:
            pairs += _flatten(item, prefix)
    elif data is not None:
        pairs.append((prefix, str(data), None))
    return pairs


def _from_json(text: str) -> list[str]:
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        return []
    try:
        data = json.loads(text[start:])
    except ValueError:
        return []
    return _lines(_flatten(data))


TAG = re.compile(r"<(?P<tag>[A-Za-z][\w.-]*)(?P<attrs>[^<>]*)>(?P<value>[^<>]+)</(?P=tag)>")
UNIT_ATTR = re.compile(r"\bunit\s*=\s*[\"']([^\"']+)[\"']", re.I)


def _from_xml(text: str) -> list[str]:
    if "</" not in text:
        return []
    pairs = []
    for m in TAG.finditer(text):
        unit = UNIT_ATTR.search(m.group("attrs") or "")
        pairs.append((m.group("tag"), m.group("value"), unit.group(1) if unit else None))
    return _lines(pairs)


def _from_csv(text: str) -> list[str]:
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if len(rows) < 3 or any(len(r) != 2 for r in rows):
        return []
    if _key(rows[0][0]) in ("field", "key", "name") and _key(rows[0][1]) in ("value", "values"):
        rows = rows[1:]
    return _lines([(k, v, None) for k, v in rows])


def _from_table(text: str) -> list[str]:
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in text.splitlines() if line.count("|") >= 2]
    rows = [r for r in rows if not all(set(c) <= set("-: ") for c in r)]
    if len(rows) < 2 or len({len(r) for r in rows}) != 1:
        return []
    header, data = rows[0], rows[1:]
    pairs = [(h, row[i], None) for row in data[:5] for i, h in enumerate(header)]
    return _lines(pairs)


def expand(body: str) -> str:
    """The body plus a plain-text reading of any structured request data in it."""
    text = body or ""
    for reader in (_from_json, _from_xml, _from_csv, _from_table):
        try:
            lines = reader(text)
        except Exception:  # never let a parser problem stop the normal reading
            lines = []
        # At least a route or weight plus one more shipment field, so ordinary mail is untouched.
        if len(lines) >= 2 and any(l.startswith(("Origin:", "Destination:", "Gross weight:")) for l in lines):
            return text + "\n\n" + "\n".join(lines)
    return text
