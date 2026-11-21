import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import settings


@dataclass(frozen=True)
class Carrier:
    name: str
    kind: str
    email: str
    serves: tuple[str, ...]


def _find(name: str, root: Path) -> Path | None:
    hits = sorted(root.rglob(name)) if root.exists() else []
    return hits[0] if hits else None


@lru_cache(maxsize=4)
def carriers(root: Path | None = None) -> dict[str, Carrier]:
    path = _find("carrier-list.csv", root or settings.kit_dir)
    if not path:
        return {}
    out = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            email = (row.get("email") or "").strip().lower()
            if email:
                out[email] = Carrier(
                    name=(row.get("name") or "").strip(),
                    kind=(row.get("kind") or "").strip().lower(),
                    email=email,
                    serves=tuple((row.get("serves") or "").split()),
                )
    return out


@lru_cache(maxsize=4)
def pickup_zones(root: Path | None = None) -> dict[str, dict]:
    path = _find("pickup_zones.csv", root or settings.kit_dir)
    if not path:
        return {}
    with path.open(newline="", encoding="utf-8") as fh:
        return {r["zone"].strip(): {"area": r["area"].strip(), "airport": r["airport"].strip()} for r in csv.DictReader(fh)}
