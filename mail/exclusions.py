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
EXCLUDE = re.compile(rf"\b(?:{VERB})\s+{NAME}")
GENERIC = {"air", "the", "any", "freight", "cargo", "airline", "airlines", "carrier", "trucks", "trucking"}
MEMORY_PATH = Path(
    os.getenv("CARRIER_EXCLUSIONS_PATH")
    or Path(__file__).resolve().parents[1] / "data" / "carrier_exclusions.json"
)


def key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def excluded_carriers(text: str) -> list[str]:
    found: list[str] = []
    for match in EXCLUDE.finditer(text or ""):
        name = match.group("name").strip()
        if key(name) in GENERIC or len(key(name)) < 3:
            continue
        found.append(name)
        if match.group("code"):
            found.append(match.group("code"))
    return found


def _load() -> dict[str, list[str]]:
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        return {str(k): [str(x) for x in v] for k, v in data.items()}
    except (OSError, ValueError, AttributeError):
        return {}


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
