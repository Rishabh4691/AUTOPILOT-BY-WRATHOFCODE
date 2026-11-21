from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import respx

from core.agents.tariff_intake import TariffIntake, seed_live_store
from core.config import load_settings
from core.contracts import Attachment, EventStatus, Mail
from sourcing.tariffs import TariffStore

KIT = Path(__file__).parent / "fixtures" / "kit"
SHEET = KIT / "yellowtail-air-freight-tariff-2026-11.txt"


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def emit(self, agent: Any, step: str, status: EventStatus, message: str, **_: Any) -> None:
        self.events.append((status.value, message))


def tariff_mail() -> Mail:
    return Mail(
        id=900,
        sender="yellowtail-air-freight@hackloop.mail",
        to="wrathofcode@hackloop.mail",
        subject="New air export tariff",
        body="Please find our new tariff attached.",
        in_reply_to=None,
        references=(),
        received_at=datetime.now(UTC),
        attachments=(Attachment(id=1, filename=SHEET.name, content_type="text/plain"),),
    )


def test_seed_copies_base_tariffs_once(tmp_path: Path) -> None:
    base = Path(__file__).resolve().parents[2] / "data" / "tariffs.json"
    live = TariffStore(tmp_path / "live.json")
    first = seed_live_store(live, base)
    assert first > 0
    assert seed_live_store(live, base) == 0
    assert len(TariffStore(tmp_path / "live.json").all()) == first


@respx.mock
async def test_tariff_mail_is_downloaded_parsed_and_stored(tmp_path: Path) -> None:
    settings = load_settings(tmp_path, {"FIVEU_API_KEY": "k", "KIT_DIR": str(KIT)})
    respx.get(f"{settings.base_url}/v1/mailbox/messages/900/attachments/1").mock(
        return_value=httpx.Response(200, content=SHEET.read_bytes())
    )
    store = TariffStore(tmp_path / "live.json")
    recorder = Recorder()
    async with httpx.AsyncClient(base_url=settings.base_url) as client:
        await TariffIntake(client, settings, store).handle(recorder, tariff_mail())
    assert any(status == "ok" and "Loaded tariff" in text for status, text in recorder.events)
    assert TariffStore(tmp_path / "live.json").all()


@respx.mock
async def test_tariff_mail_without_download_warns(tmp_path: Path) -> None:
    settings = load_settings(tmp_path, {"FIVEU_API_KEY": "k", "KIT_DIR": str(KIT)})
    respx.get(f"{settings.base_url}/v1/mailbox/messages/900/attachments/1").mock(
        return_value=httpx.Response(404)
    )
    recorder = Recorder()
    async with httpx.AsyncClient(base_url=settings.base_url) as client:
        await TariffIntake(client, settings, TariffStore(tmp_path / "x.json")).handle(
            recorder, tariff_mail()
        )
    assert recorder.events and recorder.events[0][0] == "warn"
