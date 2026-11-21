"""Tariff store: data/tariffs.json with versions by validity date.

Rule from the brief: a new monthly tariff from an airline replaces the old
one. We keep every version in the file (history) and pick, per airline, the
newest version that is valid on the quote date.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from .models import Tariff, TariffFile

DEFAULT_PATH = Path(
    os.getenv("TARIFFS_PATH", Path(__file__).resolve().parents[1] / "data" / "tariffs.json")
)


class TariffStore:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path)
        self._file = TariffFile()
        self._mtime: float | None = None
        if self.path.exists():
            self.load()

    # ---------------------------------------------------------------- io
    def load(self) -> None:
        self._file = TariffFile.model_validate_json(self.path.read_text(encoding="utf-8"))
        self._mtime = self.path.stat().st_mtime

    def reload_if_changed(self) -> None:
        if self.path.exists() and self.path.stat().st_mtime != self._mtime:
            self.load()

    def save(self) -> None:
        self._file.generated_at = datetime.now(timezone.utc)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = self._file.model_dump(mode="json")
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        os.chmod(tmp, 0o644)
        os.replace(tmp, self.path)  # atomic: readers never see half a file
        self._mtime = self.path.stat().st_mtime

    # ------------------------------------------------------------ queries
    def all(self) -> list[Tariff]:
        return list(self._file.tariffs)

    def active(self, on: date | None = None) -> list[Tariff]:
        """Per airline, only the newest version valid on `on` (default today)."""
        on = on or date.today()
        by_airline: dict[str, list[Tariff]] = defaultdict(list)
        for t in self._file.tariffs:
            if t.valid_from and t.valid_from > on:
                continue
            if t.valid_to and t.valid_to < on:
                continue
            by_airline[t.airline_code.upper()].append(t)
        result: list[Tariff] = []
        for versions in by_airline.values():
            newest = max((t.valid_from or date.min) for t in versions)
            # several files with the same start date (e.g. one per region) all stay
            result.extend(t for t in versions if (t.valid_from or date.min) == newest)
        return result

    # ------------------------------------------------------------ updates
    def upsert(self, tariff: Tariff, save: bool = True) -> list[str]:
        """Add or replace a tariff version. Returns notes for the decision log."""
        notes: list[str] = []
        kept = [t for t in self._file.tariffs if t.tariff_id != tariff.tariff_id]
        if len(kept) != len(self._file.tariffs):
            notes.append(f"replaced existing {tariff.tariff_id}")
        older = [
            t.tariff_id
            for t in kept
            if t.airline_code.upper() == tariff.airline_code.upper()
            and (t.valid_from or date.min) < (tariff.valid_from or date.min)
        ]
        if older:
            notes.append(f"{tariff.tariff_id} supersedes {', '.join(older)} from {tariff.valid_from}")
        kept.append(tariff)
        self._file.tariffs = kept
        if save:
            self.save()
        return notes
