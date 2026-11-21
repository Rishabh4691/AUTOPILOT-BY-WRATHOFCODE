"""Carriers a customer asked us not to use ("Please do not offer Zephyr Steppe Cargo (ZS)").

Round 43 quoted the one airline the customer had excluded "for this shipment or for any of our
future inquiries". The names found here are dropped from the options, and remembered per sender.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from mail.extract import sender_email

VERB = (
    r"(?:do\s+not|don'?t|never|please\s+don'?t|please\s+do\s+not|we\s+do\s+not\s+want\s+to)\s+"
    r"(?:offer|use|quote|book|ship\s+with|fly\s+with|route\s+(?:via|with|through)|propose|include)"
    r"|(?:avoid|exclude|excluding|not\s+with|nicht\s+mit|ohne|sans|sin|senza|bez)"
)
NAME = r"(?:the\s+)?(?P<name>[A-Z][A-Za-z0-9&'\-]*(?:\s+[A-Z][A-Za-z0-9&'\-]*){0,4})(?:\s*\((?P<code>[A-Z0-9]{2,3})\))?"
EXCLUDE = re.compile(rf"\b(?i:{VERB})\s+{NAME}")  # "Do not offer" at a sentence start too
# A sentence with one of these cues excludes every known airline it names: "Any airline except X",
# "X is not acceptable", "Do not book X", "Bitte kein Angebot mit X" (fuzz: only 5/15 phrasings
# were caught before). Only names from the carrier list count, so a plain mention never excludes.
NEGATED_SENTENCE = re.compile(
    r"\b(?:(?:do\s+not|don'?t|never)\s+(?:\w+\s+){0,2}?(?:offer|use|book|quote|fly|ship|route|send|want|"
    r"propose|include|work)\w*|avoid\w*|exclud\w*|except|no\s+longer|not\s+acceptable|"
    r"blacklist\w*|any\s+(?:other\s+)?(?:airline|carrier)s?\s+but|"
    r"kein\w*|nicht|ohne|sans|sin|senza|bez)\b",
    re.I,
)
GENERIC = {"air", "the", "any", "freight", "cargo", "airline", "airlines", "carrier", "trucks", "trucking"}
MEMORY_PATH = Path(
    os.getenv("CARRIER_EXCLUSIONS_PATH")
    or Path(__file__).resolve().parents[1] / "data" / "carrier_exclusions.json"
)


def key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _known_airlines() -> list[str]:
    try:
        from mail import kit

        return sorted({c.name for c in kit.carriers().values() if c.kind == "airline" and c.name})
    except Exception:
        return []


AFTER_NAME = re.compile(r"^[^.;!?]{0,25}\b(?:is|are)\s+not\s+(?:acceptable|allowed|wanted|an\s+option)", re.I)


def _mentions(sentence: str, name: str) -> list[re.Match]:
    words = [w for w in name.split() if key(w) not in GENERIC] or name.split()
    forms = {name, " ".join(words[:2])} if len(words) >= 2 else {name}
    return [m for f in forms if len(key(f)) >= 5 for m in re.finditer(rf"\b{re.escape(f)}\b", sentence, re.I)]


def excluded_by_sentence(text: str) -> list[str]:
    """Known airline names with a "no" cue right before them (within ~60 characters, same clause)
    or "... is not acceptable" right after them."""
    found: list[str] = []
    names = _known_airlines()
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", text or ""):
        for name in names:
            for m in _mentions(sentence, name):
                before = sentence[max(0, m.start() - 60) : m.start()]
                before = re.split(r"[,;]\s*(?:and|but|so)?\s*", before)[-1] if "," in before or ";" in before else before
                if (
                    NEGATED_SENTENCE.search(before)
                    or re.search(r"\bno\s+$", before, re.I)
                    or AFTER_NAME.search(sentence[m.end() :])
                ):
                    found.append(name)
                    break
    return found


def excluded_carriers(text: str) -> list[str]:
    found: list[str] = [n for n in excluded_by_sentence(text)]
    for match in EXCLUDE.finditer(text or ""):
        name = match.group("name").strip()
        if key(name) in GENERIC or len(key(name)) < 3:
            continue
        found.append(name)
        if match.group("code"):
            found.append(match.group("code"))
    return found


# Exclusions stated before this memory existed (it is only written while a mail is processed, and
# the mailbox now allows one poll per 5 s, so re-reading the whole mailbox at start fails after the
# first page). Round 42: "Please do not offer Zephyr Steppe Cargo (ZS) for this shipment or for any
# of our future inquiries."
KNOWN: dict[str, list[str]] = {"meyer-industrie@hackloop.mail": ["ZS", "Zephyr Steppe Cargo"]}


def _load() -> dict[str, list[str]]:
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        memory = {str(k): [str(x) for x in v] for k, v in data.items()}
    except (OSError, ValueError, AttributeError):
        memory = {}
    for who, names in KNOWN.items():
        memory[who] = sorted(set(memory.get(who, [])) | set(names))
    return memory


def remember(sender: str, names: list[str]) -> None:
    who = sender_email(sender)
    if not who or not names:
        return
    memory = _load()
    merged = sorted(set(memory.get(who, [])) | set(names))
    if merged == memory.get(who):
        return
    memory[who] = merged
    try:
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_PATH.write_text(json.dumps(memory, indent=1), encoding="utf-8")
    except OSError:
        pass


def learn(mails: list[dict]) -> int:
    """Rebuild the memory from every customer mail already in the mailbox.

    Round 42's customer said "do not offer Zephyr Steppe Cargo (ZS) ... for any of our future
    inquiries" before this memory existed; without this, their next request would offer it again.
    """
    from mail import kit
    from mail.text import fresh_text

    carriers = set(kit.carriers())
    changed = 0
    for m in sorted(mails, key=lambda x: int(x.get("id") or 0)):
        sender = sender_email(str(m.get("from") or ""))
        if not sender or sender in carriers or sender.endswith("@hackloop.mail") and sender.startswith(
            ("wrathofcode", "ratedesk", "tracking")
        ):
            continue
        names = excluded_carriers(fresh_text(str(m.get("body") or "")))
        if names and not set(names) <= set(recall(sender)):
            remember(sender, names)
            changed += 1
    return changed


def recall(sender: str) -> list[str]:
    return _load().get(sender_email(sender), [])


def is_excluded(carrier: str, code: str | None, excluded: list[str]) -> bool:
    keys = {key(x) for x in excluded if key(x)}
    if not keys:
        return False
    name = key(carrier)
    return name in keys or key(code or "") in keys or any(len(k) >= 5 and k in name for k in keys)
