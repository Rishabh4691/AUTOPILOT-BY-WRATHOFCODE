from __future__ import annotations

import io
import logging
import re
import time
import zipfile

import httpx

from core.contracts import Mail
from core.http import HttpGiveUp, request

log = logging.getLogger("core.attachments")

MAX_ATTACHMENT_BYTES = 2_000_000
UN_NUMBER = re.compile(r"\bUN\s?-?(\d{4})\b", re.I)
DG_FIELD = re.compile(
    r"\b(?:dangerous goods|hazardous (?:goods|materials?)|gefahrgut|DG|hazmat)\b\s*[:=]\s*"
    r"(?!\s*(?:no|none|n/?a|nein|non|keine?|not applicable|-)(?:\b|$))\s*([^\n\r;]{2,80})",
    re.I,
)
DG_CLASS = re.compile(
    r"\b(?:IATA|IMO|ADR|hazard|DG)?\s*class\s*([1-9](?:\.\d)?)\b(?=[^\n]{0,60}\b(?:dangerous|hazard|"
    r"flammable|corrosive|toxic|UN\s?\d{4}|DG)\b)",
    re.I,
)
DG_DOCUMENT_NAME = re.compile(
    r"(?:msds|\bsds\b|safety[ _-]?data|dgd|shipper'?s?[ _-]?declaration|dangerous[ _-]?goods[ _-]?declaration"
    r"|sicherheitsdatenblatt)",
    re.I,
)


def xlsx_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = archive.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            raw = archive.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            shared = [
                re.sub(r"<[^>]+>", "", item) for item in re.findall(r"<si>(.*?)</si>", raw, re.S)
            ]
        lines: list[str] = []
        for name in sorted(n for n in names if n.startswith("xl/worksheets/sheet")):
            sheet = archive.read(name).decode("utf-8", "replace")
            for row in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
                cells: list[str] = []
                for cell in re.findall(r"<c([^>]*)>(.*?)</c>", row, re.S):
                    attrs, inner = cell
                    value = re.search(r"<v>(.*?)</v>", inner, re.S)
                    inline = re.search(r"<t[^>]*>(.*?)</t>", inner, re.S)
                    if 't="s"' in attrs and value and value.group(1).isdigit():
                        index = int(value.group(1))
                        cells.append(shared[index] if index < len(shared) else "")
                    elif inline:
                        cells.append(inline.group(1))
                    elif value:
                        cells.append(value.group(1))
                lines.append(" | ".join(cells))
        return "\n".join(lines)


def docx_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        raw = archive.read("word/document.xml").decode("utf-8", "replace")
    raw = re.sub(r"</w:p>", "\n", raw)
    return re.sub(r"<[^>]+>", "", raw)


def pdf_text(content: bytes) -> str:
    try:
        from sourcing.kit_parsers import pdf_lines

        return "\n".join(pdf_lines(content))
    except Exception as error:
        log.info("pdf_text_unavailable", extra={"error": type(error).__name__})
        return ""


def to_text(filename: str, content: bytes) -> str:
    name = filename.lower()
    try:
        if name.endswith((".xlsx", ".xlsm")):
            return xlsx_text(content)
        if name.endswith(".docx"):
            return docx_text(content)
        if name.endswith(".pdf"):
            return pdf_text(content)
        if name.endswith((".csv", ".txt", ".json", ".tsv")):
            return content.decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError, ValueError) as error:
        log.info("attachment_unreadable", extra={"file": filename, "error": type(error).__name__})
    return ""


def dangerous_goods(text: str) -> str | None:
    un = UN_NUMBER.search(text)
    field = DG_FIELD.search(text)
    dg_class = DG_CLASS.search(text)
    if field:
        return field.group(1).strip()
    if un:
        return f"UN{un.group(1)}"
    if dg_class:
        return f"class {dg_class.group(1)}"
    return None


def has_dg_documents(mail: Mail) -> bool:
    return any(DG_DOCUMENT_NAME.search(a.filename) for a in mail.attachments)


class AttachmentReader:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def text(self, mail: Mail) -> str:
        parts: list[str] = []
        for attachment in mail.attachments:
            if attachment.size is not None and attachment.size > MAX_ATTACHMENT_BYTES:
                continue
            try:
                response = await request(
                    self.client,
                    "GET",
                    f"/v1/mailbox/messages/{mail.id}/attachments/{attachment.id}",
                    deadline=time.monotonic() + 15,
                )
            except HttpGiveUp:
                continue
            if response.status_code == 200:
                parts.append(to_text(attachment.filename, response.content))
        return "\n".join(part for part in parts if part)
