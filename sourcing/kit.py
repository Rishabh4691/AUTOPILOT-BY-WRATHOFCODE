"""Start kit: carrier list, pickup zones, and building data/tariffs.json.

    python -m sourcing.kit                # parse data/kit -> data/tariffs.json
    python -m sourcing.kit --check        # parse and report, write nothing
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from .bids import Carrier
from .kit_parsers import parse_file
from .models import Tariff
from .tariffs import TariffStore

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "data" / "kit"
SHEET_EXT = (".xlsx", ".xls", ".pdf", ".docx", ".txt", ".jpg", ".jpeg", ".png")


def load_carriers(path: Path = KIT / "carrier-list.csv") -> list[Carrier]:
    """name,kind,email,serves -> Carrier. Airlines serve IATA codes, truckers zones."""
    out: list[Carrier] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kind = row["kind"].strip().lower()
            serves = row["serves"].split()
            email = row["email"].strip()
            out.append(
                Carrier(
                    name=row["name"].strip(),
                    email=email,
                    kind="trucker" if kind == "trucker" else "airline",
                    airline_code=email.split("@")[0] if kind == "airline" else None,
                    destinations=serves if kind == "airline" else [],
                    zones=serves if kind == "trucker" else [],
                )
            )
    return out


def load_pickup_zones(path: Path = KIT / "pickup_zones.csv") -> dict[str, dict]:
    """zone -> {'area': 'Frankfurt am Main', 'airport': 'FRA'}"""
    with open(path, newline="", encoding="utf-8") as f:
        return {
            r["zone"].strip(): {"area": r["area"].strip(), "airport": r["airport"].strip()}
            for r in csv.DictReader(f)
        }


def zone_for_postcode(postcode: str | None) -> str | None:
    """German postcodes: the zone is the first two digits (60311 -> '60')."""
    digits = "".join(ch for ch in (postcode or "") if ch.isdigit())
    return digits[:2] if len(digits) >= 2 else None


def airport_for_zone(zone: str | None, zones: dict[str, dict] | None = None) -> str | None:
    zones = zones if zones is not None else load_pickup_zones()
    return (zones.get(zone or "") or {}).get("airport")


def sheet_files(kit: Path = KIT) -> list[Path]:
    """One input per airline. A '<name>.verified.txt' replaces scanned pages of that name."""
    files = sorted(p for p in kit.iterdir() if p.suffix.lower() in SHEET_EXT)
    verified = [p for p in files if p.name.endswith(".verified.txt")]
    stems = {p.name.removesuffix(".verified.txt") for p in verified}

    def replaced(p: Path) -> bool:
        return any(p.name.startswith(s) and p not in verified for s in stems)

    return [p for p in files if not replaced(p)]


def build(kit: Path = KIT, out: Path | None = ROOT / "data" / "tariffs.json") -> tuple[list[Tariff], list[str]]:
    tariffs: list[Tariff] = []
    problems: list[str] = []
    for p in sheet_files(kit):
        try:
            t, probs = parse_file(p.name, p.read_bytes())
        except Exception as e:  # report and keep going
            problems.append(f"{p.name}: {type(e).__name__}: {e}")
            continue
        problems += [f"{p.name}: {x}" for x in probs]
        t.source_file = p.name
        tariffs.append(t)
    if out is not None:
        store = TariffStore(out)
        for t in tariffs:
            store.upsert(t, save=False)
        store.save()
    return tariffs, problems


def main(argv: list[str]) -> int:
    check = "--check" in argv
    tariffs, problems = build(out=None if check else ROOT / "data" / "tariffs.json")
    for t in tariffs:
        print(f"{t.airline:<24} {t.source_file:<52} {len(t.lanes):>3} lanes  {t.currency} "
              f"{t.valid_from}..{t.valid_to}")
    print(f"{len(tariffs)} tariffs, {sum(len(t.lanes) for t in tariffs)} lanes")
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
