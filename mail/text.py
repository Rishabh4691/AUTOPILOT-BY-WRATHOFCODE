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


def reply_subject(subject: str) -> str:
    s = (subject or "").strip()
    return s if s.lower().startswith(("re:", "aw:", "sv:", "rif:", "réf:")) else f"Re: {s}".strip()
