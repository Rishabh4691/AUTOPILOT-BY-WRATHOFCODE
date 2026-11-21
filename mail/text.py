import re

QUOTE_CUTS = [
    r"^\s*>.*$",
    r"^\s*(on|am|le|el|il|w dniu)\b.{0,120}(wrote|schrieb|a écrit|escribió|ha scritto|napisał).*$",
    r"^-{2,}\s*(original message|ursprüngliche nachricht|message d'origine|mensaje original|messaggio originale)\s*-{2,}.*$",
    r"^\s*(from|von|de|da|od):\s.*@.*$",
    r"^\s*_{8,}\s*$",
]
HEADER_FROM = re.compile(r"^\s*(from|von|de|da|od):\s.+$", re.I)
HEADER_NEXT = re.compile(
    r"^\s*(sent|gesendet|envoyé|enviado|inviato|wysłano|date|datum|fecha|data):\s", re.I
)


def fresh_text(body: str) -> str:
    lines = []
    raw = (body or "").splitlines()
    for i, line in enumerate(raw):
        low = line.lower()
        if any(re.match(p, low, re.I) for p in QUOTE_CUTS[1:]):
            break
        # Outlook history without an address: "From: Sales Team" followed by "Sent: ...".
        if HEADER_FROM.match(line) and i + 1 < len(raw) and HEADER_NEXT.match(raw[i + 1]):
            break
        if re.match(QUOTE_CUTS[0], line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


FORWARD_SUBJECT = re.compile(r"^\s*(?:(?:re|aw)\s*:\s*)*(?:fw|fwd|wg|tr|rv|i)\s*:", re.I)
FORWARD_MARK = re.compile(
    r"^\s*(?:-{2,}\s*(?:forwarded message|weitergeleitete nachricht|message transféré|mensaje reenviado|"
    r"messaggio inoltrato|original message|ursprüngliche nachricht)\s*-{2,}|begin forwarded message:?)\s*$|"
    r"^\s*(?:from|von|de|da|od):\s.+$",
    re.I,
)
FORWARD_HEADER = re.compile(
    r"^\s*(?:from|von|de|da|od|sent|gesendet|envoyé|enviado|inviato|wysłano|date|datum|fecha|data|to|an|à|para|a|do|"
    r"cc|subject|betreff|objet|asunto|oggetto|temat):\s",
    re.I,
)
HAS_CARGO = re.compile(r"\d\s*(?:kgs?|kilos?|lbs?|cbm|m3|m³)\b|\d\s*[x×*]\s*\d", re.I)


def request_text(subject: str, body: str) -> str:
    """The text that holds the request.

    Normally the new message only. A forward ("FW: ...", "please quote the request
    below") carries the customer's request in the quoted part, so when the new
    text has no cargo figures, the first forwarded message is used instead.
    """
    fresh = fresh_text(body)
    if not FORWARD_SUBJECT.match(subject or "") or HAS_CARGO.search(fresh):
        return fresh
    lines = (body or "").splitlines()
    start = next((i for i, line in enumerate(lines) if FORWARD_MARK.match(line)), None)
    if start is None:
        return fresh
    rest = lines[start + 1 :] if not FORWARD_HEADER.match(lines[start]) else lines[start:]
    while rest and (FORWARD_HEADER.match(rest[0]) or not rest[0].strip()):
        rest = rest[1:]
    quoted = [re.sub(r"^\s*>\s?", "", line) for line in rest]
    forwarded = fresh_text("\n".join(quoted))
    return forwarded if HAS_CARGO.search(forwarded) else fresh


def reply_subject(subject: str) -> str:
    s = (subject or "").strip()
    return s if s.lower().startswith(("re:", "aw:", "sv:", "rif:", "réf:")) else f"Re: {s}".strip()
