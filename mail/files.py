import base64
import html
import io
import logging
import os
import re
import zipfile
from email import message_from_bytes, policy

log = logging.getLogger("mail.files")

TEXT_EXT = (".txt", ".csv", ".tsv", ".json", ".md", ".log", ".xml", ".yaml", ".yml")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp")
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".ogg", ".oga", ".opus", ".flac", ".aac", ".wma", ".amr")
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".wmv", ".3gp", ".mpeg", ".mpg")
MAX_DEPTH = 2
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
SPEECH_HINT = (
    "Air freight quotation request. Pickup postcode, airport code, destination, pieces, pallets, "
    "gross weight in kilograms, volume in cubic metres, dimensions in centimetres, ready date."
)

_whisper: dict = {}


def kind(filename: str, content_type: str = "", data: bytes = b"") -> str:
    name = (filename or "").lower()
    ctype = (content_type or "").lower()
    if name.endswith(IMAGE_EXT) or ctype.startswith("image/"):
        return "image"
    if name.endswith(AUDIO_EXT) or ctype.startswith("audio/"):
        return "audio"
    if name.endswith(VIDEO_EXT) or ctype.startswith("video/"):
        return "video"
    if name.endswith(".pdf") or ctype == "application/pdf" or data[:5] == b"%PDF-":
        return "pdf"
    if name.endswith((".docx", ".docm", ".dotx", ".dotm")):
        return "docx"
    if name.endswith((".doc", ".dot")):
        return "doc"
    for ext in (".xlsx", ".xlsm", ".xls", ".pptx", ".odt", ".ods", ".odp", ".rtf", ".zip"):
        if name.endswith(ext):
            return ext[1:]
    if name.endswith((".html", ".htm")) or "html" in ctype:
        return "html"
    if name.endswith(".eml") or ctype == "message/rfc822":
        return "eml"
    if name.endswith(TEXT_EXT) or ctype.startswith("text/"):
        return "text"
    if data[:4] == b"PK\x03\x04":
        return _zip_kind(data)
    if data[:8] == OLE_MAGIC:
        return "doc" if "WordDocument".encode("utf-16-le") in data[:65536] or b"WordDocument" in data else "xls"
    if data[:5] == b"{\\rtf":
        return "rtf"
    if data[:3] == b"ID3" or data[:4] in (b"RIFF", b"OggS", b"fLaC"):
        return "audio"
    if data[4:8] == b"ftyp":
        return "video"
    if data[:4] in (b"\x89PNG", b"GIF8") or data[:3] == b"\xff\xd8\xff":
        return "image"
    return "text" if _looks_textual(data) else "unknown"


def _zip_kind(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
    except zipfile.BadZipFile:
        return "unknown"
    if "word/document.xml" in names:
        return "docx"
    if any(n.startswith("xl/") for n in names):
        return "xlsx"
    if any(n.startswith("ppt/") for n in names):
        return "pptx"
    if "content.xml" in names:
        return "odt"
    return "zip"


def _looks_textual(data: bytes) -> bool:
    sample = data[:2000]
    if not sample or b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def decode(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


def file_text(filename: str, data: bytes, content_type: str = "", depth: int = 0) -> str:
    k = kind(filename, content_type, data)
    try:
        text = READERS.get(k, lambda _d: "")(data) if k != "zip" else zip_text(data, depth)
    except Exception as error:
        log.info("attachment_unreadable", extra={"file": filename, "kind": k, "error": type(error).__name__})
        text = ""
    if not text.strip() and k == "image":
        text = vision_text(data, content_type or "image/png")
    log.info("attachment_read", extra={"file": filename, "kind": k, "chars": len(text)})
    return text.strip()


def xlsx_text(data: bytes) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None and str(c).strip()]
            if cells:
                lines.append(": ".join(cells) if len(cells) == 2 else " | ".join(cells))
    return "\n".join(lines)


def xls_text(data: bytes) -> str:
    import xlrd

    book = xlrd.open_workbook(file_contents=data)
    lines = []
    for sheet in book.sheets():
        for r in range(sheet.nrows):
            cells = [str(c).removesuffix(".0") for c in sheet.row_values(r) if str(c).strip()]
            if cells:
                lines.append(": ".join(cells) if len(cells) == 2 else " | ".join(cells))
    return "\n".join(lines)


def _xml_text(xml: str, para: str) -> str:
    xml = re.sub(para, "\n", xml)
    xml = re.sub(r"<(?:w:tab|text:tab|a:tab)\s*/>", "\t", xml)
    xml = re.sub(r"</(?:w:tc|table:table-cell|a:tc)>", " | ", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        parts = [n for n in z.namelist() if re.match(r"word/(document|header\d*|footer\d*|footnotes)\.xml$", n)]
        parts.sort(key=lambda n: n != "word/document.xml")
        return "\n".join(_xml_text(z.read(n).decode("utf-8", "ignore"), r"</w:p>") for n in parts)


def doc_text(data: bytes) -> str:
    try:
        import olefile

        with olefile.OleFileIO(io.BytesIO(data)) as ole:
            data = ole.openstream("WordDocument").read()
    except Exception:
        pass
    printable = r"[\t\n\r\x20-\x7e\xa0-\xff\u2018-\u201e\u20ac]{4,}"
    texts = []
    for start in (0, 1):
        chunk = data[start : start + (len(data) - start) // 2 * 2]
        texts.append("\n".join(re.findall(printable, chunk.decode("utf-16-le", "ignore"))))
    texts.append("\n".join(re.findall(printable.replace("{4,}", "{6,}"), data.decode("cp1252", "ignore"))))
    best = max(texts, key=lambda t: len(re.findall(r"[A-Za-z]{3,}", t)))
    return re.sub(r"\r", "\n", best)


def pptx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        slides = sorted(
            (n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
            key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)),
        )
        return "\n".join(_xml_text(z.read(n).decode("utf-8", "ignore"), r"</a:p>") for n in slides)


def odf_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return _xml_text(z.read("content.xml").decode("utf-8", "ignore"), r"</text:(?:p|h)>|</table:table-row>")


def rtf_text(data: bytes) -> str:
    text = decode(data)
    text = re.sub(r"\\'([0-9a-f]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1252"), text)
    text = re.sub(r"\\(?:par|line)\b ?", "\n", text)
    text = re.sub(r"\\tab\b ?", "\t", text)
    text = re.sub(r"\{\\\*[^{}]*\}|\\[a-z]+-?\d* ?|[{}]", "", text)
    return text


def html_text(data: bytes | str) -> str:
    raw = decode(data) if isinstance(data, bytes) else data
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", raw)
    raw = re.sub(r"(?i)</t[dh]>", " | ", raw)
    return html.unescape(re.sub(r"<[^>]+>", "", raw))


def eml_text(data: bytes) -> str:
    msg = message_from_bytes(data, policy=policy.default)
    parts = [f"Subject: {msg.get('subject', '')}"]
    for part in msg.walk():
        if part.is_multipart():
            continue
        name = part.get_filename() or ""
        payload = part.get_payload(decode=True) or b""
        if name:
            parts.append(file_text(name, payload, part.get_content_type(), MAX_DEPTH))
        elif part.get_content_type() == "text/plain":
            parts.append(decode(payload))
        elif part.get_content_type() == "text/html":
            parts.append(html_text(payload))
    return "\n".join(p for p in parts if p)


def zip_text(data: bytes, depth: int = 0) -> str:
    if depth >= MAX_DEPTH:
        return ""
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist()[:10]:
            if info.is_dir() or info.file_size > 25_000_000:
                continue
            text = file_text(info.filename, z.read(info), "", depth + 1)
            if text:
                out.append(f"[{info.filename}]\n{text}")
    return "\n\n".join(out)


def ocr(image) -> str:
    import pytesseract

    image = image.convert("L")
    if image.width < 1200:
        image = image.resize((image.width * 2, image.height * 2))
    return pytesseract.image_to_string(image)


def image_text(data: bytes) -> str:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        return ocr(img)


def pdf_text(data: bytes) -> str:
    import pdfplumber

    pages = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:10]:
            text = page.extract_text() or ""
            if len(text.strip()) < 20:
                try:
                    text = ocr(page.to_image(resolution=200).original)
                except Exception as error:
                    log.info("pdf_ocr_failed", extra={"error": type(error).__name__})
            pages.append(text)
    return "\n".join(pages)


def _speech_model():
    if "model" not in _whisper:
        from faster_whisper import WhisperModel

        name = os.getenv("WHISPER_MODEL", "small")
        _whisper["model"] = WhisperModel(name, device="cpu", compute_type="int8")
    return _whisper["model"]


def warm_speech() -> bool:
    try:
        _speech_model()
        return True
    except Exception as error:
        log.warning("speech_unavailable", extra={"error": type(error).__name__})
        return False


def speech_text(data: bytes) -> str:
    try:
        model = _speech_model()
    except ImportError:
        log.warning("speech_unavailable", extra={"hint": "pip install faster-whisper"})
        return ""
    segments, _info = model.transcribe(io.BytesIO(data), beam_size=5, vad_filter=True, initial_prompt=SPEECH_HINT)
    return " ".join(s.text.strip() for s in segments)


def video_frames_text(data: bytes, frames: int = 4) -> str:
    import av

    seen: list[str] = []
    with av.open(io.BytesIO(data)) as container:
        stream = next((s for s in container.streams if s.type == "video"), None)
        if stream is None:
            return ""
        duration = float(container.duration or 0) / 1_000_000
        stamps = [duration * (i + 0.5) / frames for i in range(frames)] if duration else [0.0]
        for t in stamps:
            container.seek(int(t * 1_000_000), any_frame=False, backward=True)
            frame = next(container.decode(stream), None)
            if frame is None:
                continue
            for line in ocr(frame.to_image()).splitlines():
                line = line.strip()
                if len(line) > 2 and line not in seen:
                    seen.append(line)
    return "\n".join(seen)


def video_text(data: bytes) -> str:
    parts = []
    try:
        parts.append(speech_text(data))
    except Exception as error:
        log.info("video_speech_failed", extra={"error": type(error).__name__})
    try:
        parts.append(video_frames_text(data))
    except Exception as error:
        log.info("video_frames_failed", extra={"error": type(error).__name__})
    return "\n".join(p for p in parts if p)


def vision_text(data: bytes, mime: str) -> str:
    if os.getenv("VISION_FALLBACK", "1") == "0" or len(data) > 8_000_000:
        return ""
    import httpx

    from .config import settings

    if not settings.api_key:
        return ""
    url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    body = {
        "model": os.getenv("VISION_MODEL", "gpt-4.1-mini"),
        "max_completion_tokens": 600,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Copy all text in this image exactly, keep numbers and units. Text only."},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ],
    }
    try:
        r = httpx.post(
            f"{settings.gateway_url}/chat/completions",
            json=body,
            headers={"X-API-Key": settings.api_key, "Authorization": f"Bearer {settings.api_key}"},
            timeout=30,
        )
        if r.status_code >= 400:
            log.info("vision_failed", extra={"status": r.status_code})
            return ""
        return r.json()["choices"][0]["message"]["content"] or ""
    except Exception as error:
        log.info("vision_failed", extra={"error": type(error).__name__})
        return ""


READERS = {
    "text": decode,
    "xlsx": xlsx_text,
    "xlsm": xlsx_text,
    "xls": xls_text,
    "ods": odf_text,
    "docx": docx_text,
    "doc": doc_text,
    "pptx": pptx_text,
    "odt": odf_text,
    "odp": odf_text,
    "rtf": rtf_text,
    "html": html_text,
    "eml": eml_text,
    "pdf": pdf_text,
    "image": image_text,
    "audio": speech_text,
    "video": video_text,
}


class TextCache:
    def __init__(self, size: int = 200) -> None:
        self.size = size
        self.items: dict[tuple[int, int], tuple[str, str]] = {}

    def get(self, mail_id: int, attachment_id: int) -> tuple[str, str] | None:
        return self.items.get((mail_id, attachment_id))

    def put(self, mail_id: int, attachment_id: int, filename: str, text: str) -> None:
        if len(self.items) >= self.size:
            self.items.pop(next(iter(self.items)))
        self.items[(mail_id, attachment_id)] = (filename, text)


CACHE = TextCache()
