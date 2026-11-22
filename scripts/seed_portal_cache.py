"""Fill data/portal_cache.jsonl from portal prices already in the mailbox (rate desk replies).

    python scripts/seed_portal_cache.py mails.json [--out data/portal_cache.jsonl]

mails.json is a list of mailbox messages (id, from, subject, body, received_at). Each rate desk
reply ("portal rates for DUS-MEX, 1124.0 kg, 6.8 cbm ...: - Xenon Cargo Airlines (XC): 2.00 EUR,
2 days, rate_id ...") is a real portal price. Read-only on the mailbox; writes only the cache file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourcing import portal_cache

HEAD = re.compile(
    r"portal rates for ([A-Z]{3})-([A-Z]{3}),\s*([\d.]+)\s*kg(?:,\s*([\d.]+)\s*cbm)?", re.I
)
LINE = re.compile(
    r"^-\s*(.+?)\s*\(([A-Z0-9]{2,3})\):\s*([\d.,]+)\s*([A-Z]{3}),\s*(\d+)\s*days?", re.M
)


def chargeable(gross: Decimal, cbm: Decimal | None) -> Decimal:
    raw = max(gross, (cbm or Decimal(0)) * Decimal(167))
    return (raw / Decimal("0.5")).to_integral_value(rounding=ROUND_CEILING) * Decimal("0.5")


def rows_from(mail: dict) -> list[tuple]:
    if "ratedesk" not in str(mail.get("from", "")).lower():
        return []
    body = mail.get("body") or ""
    head = HEAD.search(body)
    if not head:
        return []
    origin, dest = head.group(1).upper(), head.group(2).upper()
    kg = chargeable(Decimal(head.group(3)), Decimal(head.group(4)) if head.group(4) else None)
    out = []
    for m in LINE.finditer(body):
        out.append((origin, dest, m.group(1).strip(), m.group(2), kg,
                    Decimal(m.group(3).replace(",", "")), m.group(4), int(m.group(5))))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mails")
    ap.add_argument("--out", default=str(portal_cache.cache_path()))
    args = ap.parse_args()
    mails = json.loads(Path(args.mails).read_text())
    seen = set()
    n = 0
    for mail in sorted(mails, key=lambda m: m.get("id", 0)):
        for row in rows_from(mail):
            key = row[:6]
            if key in seen:
                continue
            seen.add(key)
            origin, dest, airline, code, kg, total, cur, days = row
            portal_cache.record(origin, dest, airline, code, kg, total, cur, days, path=Path(args.out))
            n += 1
    print(f"{n} portal prices written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
