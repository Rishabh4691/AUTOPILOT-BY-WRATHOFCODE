from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ContactKind = Literal["airline", "trucker"]


@dataclass(frozen=True)
class Contact:
    name: str
    kind: ContactKind
    email: str
    serves: frozenset[str]


@dataclass(frozen=True)
class Zone:
    zone: str
    area: str
    airport: str


@dataclass(frozen=True)
class CarrierDirectory:
    contacts: tuple[Contact, ...]
    zones: tuple[Zone, ...]

    def by_email(self, address: str) -> Contact | None:
        wanted = address.strip().lower()
        return next((c for c in self.contacts if c.email == wanted), None)

    def airlines(self) -> tuple[Contact, ...]:
        return tuple(c for c in self.contacts if c.kind == "airline")

    def airlines_serving(self, destination: str) -> tuple[Contact, ...]:
        code = destination.strip().upper()
        return tuple(c for c in self.airlines() if code in c.serves)

    def truckers_for_zone(self, zone: str) -> tuple[Contact, ...]:
        wanted = zone.strip()
        return tuple(c for c in self.contacts if c.kind == "trucker" and wanted in c.serves)

    def zone(self, zone: str) -> Zone | None:
        wanted = zone.strip()
        return next((z for z in self.zones if z.zone == wanted), None)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [
            {k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)
        ]


def load_directory(kit_dir: Path) -> CarrierDirectory:
    root = kit_dir / "start-kit" if (kit_dir / "start-kit").is_dir() else kit_dir
    contacts = tuple(
        Contact(
            name=row["name"],
            kind="trucker" if row["kind"].lower() == "trucker" else "airline",
            email=row["email"].lower(),
            serves=frozenset(row["serves"].upper().split()),
        )
        for row in _rows(root / "carrier-list.csv")
        if row.get("email")
    )
    zones = tuple(
        Zone(zone=row["zone"], area=row["area"], airport=row["airport"].upper())
        for row in _rows(root / "pickup_zones.csv")
        if row.get("zone")
    )
    return CarrierDirectory(contacts=contacts, zones=zones)
