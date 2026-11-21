from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from core.config import Settings
from core.contracts import Agent, EventStatus, Mail
from core.http import HttpGiveUp, request
from sourcing.ingest import ingest_tariff_mail
from sourcing.kit import load_carriers
from sourcing.tariffs import TariffStore

log = logging.getLogger("core.tariff_intake")

BASE_TARIFFS = Path(__file__).resolve().parents[2] / "data" / "tariffs.json"
LIVE_TARIFFS = BASE_TARIFFS.with_name("tariffs.live.json")


def carrier_list_path(settings: Settings) -> Path:
    nested = settings.kit_dir / "start-kit" / "carrier-list.csv"
    return nested if nested.exists() else settings.kit_dir / "carrier-list.csv"


def live_store() -> TariffStore:
    from sourcing import sheets

    store: TariffStore = sheets._store()
    if store.path.resolve() == BASE_TARIFFS.resolve():
        store = TariffStore(LIVE_TARIFFS)
        sheets._default_store = store
    return store


def seed_live_store(live: TariffStore, base_path: Path = BASE_TARIFFS) -> int:
    if not base_path.exists() or live.path.resolve() == base_path.resolve():
        return 0
    known = {tariff.tariff_id for tariff in live.all()}
    added = 0
    for tariff in TariffStore(base_path).all():
        if tariff.tariff_id not in known:
            live.upsert(tariff, save=False)
            added += 1
    if added:
        live.save()
    return added


def as_message(mail: Mail) -> dict[str, Any]:
    return {
        "id": mail.id,
        "from": mail.sender,
        "to": mail.to,
        "subject": mail.subject,
        "body": mail.body,
        "attachments": [
            {"id": a.id, "filename": a.filename, "content_type": a.content_type}
            for a in mail.attachments
        ],
    }


class TariffIntake:
    def __init__(
        self, client: httpx.AsyncClient, settings: Settings, store: TariffStore | None = None
    ) -> None:
        self.client = client
        self.settings = settings
        self.store = store

    async def download(self, mail: Mail) -> list[tuple[str, bytes]]:
        files: list[tuple[str, bytes]] = []
        for attachment in mail.attachments:
            try:
                response = await request(
                    self.client,
                    "GET",
                    f"/v1/mailbox/messages/{mail.id}/attachments/{attachment.id}",
                    deadline=time.monotonic() + 30,
                )
            except HttpGiveUp as error:
                log.warning("tariff_download_failed", extra={"mail": mail.id, "error": str(error)})
                continue
            if response.status_code == 200:
                files.append((attachment.filename, response.content))
        return files

    async def handle(self, orch: Any, mail: Mail) -> None:
        files = await self.download(mail)
        if not files:
            orch.emit(
                Agent.TARIFF,
                "tariff",
                EventStatus.WARN,
                f"Tariff mail {mail.id} from {mail.sender} had no readable attachment.",
            )
            return
        store = self.store or live_store()
        carriers = load_carriers(carrier_list_path(self.settings))
        result = await asyncio.to_thread(
            ingest_tariff_mail,
            as_message(mail),
            files,
            carriers,
            store,
            datetime.now(UTC).date(),
        )
        for tariff_id in result.stored:
            orch.emit(
                Agent.TARIFF,
                "tariff",
                EventStatus.OK,
                f"Loaded tariff {tariff_id} from {mail.sender}.",
            )
        for alarm in result.alarms:
            orch.emit(Agent.TARIFF, "tariff", EventStatus.WARN, f"Tariff problem: {alarm}"[:300])
        log.info(
            "tariff_ingested",
            extra={"mail": mail.id, "stored": result.stored, "alarms": len(result.alarms)},
        )
