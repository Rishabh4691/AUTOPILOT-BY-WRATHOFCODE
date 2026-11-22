"""Requests that point back to an earlier one ("the same shipment as in my earlier request ...").

Round 103: "Could you please quote the same shipment as in my earlier request, 'Air freight quote
request: STR to MEL' ... The new destination is LAX, and the shipment will be ready for pickup on
2026-11-29 ... cheapest option." The cargo and pickup come from that earlier request; only the
destination, ready date and preference change.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

PATH = Path(os.getenv("CUSTOMER_REQUESTS_PATH") or Path(__file__).resolve().parents[1] / "data" / "customer_requests.json")
REFERS_BACK = re.compile(
    r"same shipment|same cargo|earlier request|previous request|my last request|as before|"
    r"(?:cargo|shipment|pickup)[^.\n]{0,40}(?:details )?(?:are |is )?unchanged|you already have (?:them|the details)|"
    r"gleiche sendung|selbe sendung|frühere anfrage|vorherige anfrage|wie zuvor",
    re.I,
)
NEW_DEST = re.compile(r"(?:new destination|destination is now|now to|neues ziel|neuer zielflughafen)\D{0,20}\b([A-Z]{3})\b", re.I)
SUBJECT_DEST = re.compile(r"\bto ([A-Z]{3})\b")
DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
QUOTED_SUBJECT = re.compile(r"[\"“'„]([^\"”'“]{6,120})[\"”'“]")


def _load() -> dict[str, list[dict]]:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def remember(sender: str, subject: str, body: str) -> None:
    who = (sender or "").strip().lower()
    if not who or not body:
        return
    data = _load()
    items = [i for i in data.get(who, []) if i.get("subject") != subject][-19:]
    items.append({"subject": subject, "body": body})
    data[who] = items
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def rebuild(sender: str, subject: str, body: str) -> str | None:
    """The earlier request's text with this mail's destination, date and preference, or None."""
    if not REFERS_BACK.search(body or ""):
        return None
    items = _load().get((sender or "").strip().lower(), [])
    if not items:
        return None
    quoted = QUOTED_SUBJECT.search(body)
    earlier = None
    if quoted:
        want = quoted.group(1).strip().lower()
        earlier = next((i for i in reversed(items) if i["subject"].strip().lower() == want), None)
        earlier = earlier or next((i for i in reversed(items) if want in i["subject"].lower()), None)
    if quoted and earlier is None:
        # The customer named a request we do not have: never guess with another one (round 104 check).
        return None
    earlier = earlier or items[-1]
    text = earlier["body"]
    dest = NEW_DEST.search(body) or SUBJECT_DEST.search(subject or "")
    if dest:
        # The destination is the code followed by its city ("MEL (Melbourne, AU)"); "deliver it to STR"
        # names the origin and must stay.
        old = re.findall(r"\b([A-Z]{3})\s*\(", text) or re.findall(r"\bto ([A-Z]{3})\b(?!\s+ourselves)", text)[-1:]
        for code in set(old):
            if code != dest.group(1).upper():
                text = re.sub(rf"\b{code}\b", dest.group(1).upper(), text)
    # The ready date, not "sent on 2026-11-21" about the earlier mail.
    ready = re.search(r"(?:ready|abholbereit|bereit|available)[^.\n]{0,40}?(20\d\d-\d\d-\d\d)", body, re.I)
    dates = DATE.findall(body)
    new_date = ready.group(1) if ready else (dates[-1] if dates else None)
    if new_date:
        text = DATE.sub(new_date, text, count=1)
    # The earlier request's deadline belonged to its own destination and date (round 104: ATL).
    text = " ".join(s for s in re.split(r"(?<=[.!?])\s+", text)
                    if not re.search(r"no later than|deadline|must arrive|spätestens|among the options", s, re.I))
    if re.search(r"\bcheapest\b|\bgünstigst", body, re.I):
        text = re.sub(r"\bfastest\b", "cheapest", text, flags=re.I) + "\nPlease quote the cheapest option."
    elif re.search(r"\bfastest\b|\bschnellst", body, re.I):
        text = re.sub(r"\bcheapest\b", "fastest", text, flags=re.I) + "\nPlease quote the fastest option."
    return text
