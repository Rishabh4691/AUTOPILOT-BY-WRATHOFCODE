from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from core.agents.airline_bids import AirlineBidSource
from core.agents.attachments import AttachmentReader
from core.agents.booking import BookingAgent
from core.agents.classifier import RuleClassifier
from core.agents.dg_guard import DgGuard
from core.agents.directory import load_directory
from core.agents.extractor import RegexRfqExtractor
from core.agents.human_writer import HumanEmailWriter
from core.agents.mailbox import DryRunMailbox, HttpMailboxClient
from core.agents.portal import PortalPriceSource
from core.agents.rules_extractor import RulesFirstExtractor
from core.agents.sheets import SheetPriceSource
from core.agents.sourcing_adapter import SourcingPortalPriceSource
from core.agents.tariff_intake import TariffIntake, live_store, seed_live_store
from core.agents.tracking import TrackingAgent
from core.agents.trucker import EmailTruckerPickupSource
from core.config import Settings, auth_headers, load_settings
from core.contracts import MailboxClient, Stage
from core.llm import GatewayLlmClient
from core.orchestrator import Orchestrator
from core.outbound import DirectoryMailSender
from core.store import SqliteEventSink, Store
from core.timing import is_stale
from mail.lock import AlreadyRunning, single_instance

log = logging.getLogger("core.main")

RESERVED_LOG_KEYS = frozenset(vars(logging.makeLogRecord({})))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(
            {k: v for k, v in vars(record).items() if k not in RESERVED_LOG_KEYS and k != "message"}
        )
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info).splitlines()[-1]
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    for noisy in ("httpx", "httpcore", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def build(settings: Settings, client: httpx.AsyncClient, store: Store) -> Orchestrator:
    directory = load_directory(settings.kit_dir)
    llm = GatewayLlmClient(settings)
    http_mailbox = HttpMailboxClient(client, settings)
    mailbox: MailboxClient = (
        DryRunMailbox(http_mailbox, settings.our_address) if settings.dry_run else http_mailbox
    )
    sender = DirectoryMailSender(client, settings, directory)
    portal = PortalPriceSource(client, settings, lambda: datetime.now(UTC))
    dg = DgGuard(client, settings)
    portal_source = SourcingPortalPriceSource(settings, lambda: datetime.now(UTC))
    return Orchestrator(
        settings=settings,
        store=store,
        mailbox=mailbox,
        classifier=RuleClassifier(settings, directory),
        extractor=RulesFirstExtractor(RegexRfqExtractor(settings, llm), attachments=dg.texts),
        sources=[
            portal_source,
            SheetPriceSource(),
        ],
        pickup=EmailTruckerPickupSource(
            directory,
            sender,
            lambda: datetime.now(UTC),
            history_path=settings.db_path.with_name("pickup_history.jsonl"),
        ),
        writer=HumanEmailWriter(client),
        events=SqliteEventSink(store),
        booker=BookingAgent(client, settings, portal, directory, outbound=sender),
        tracker=TrackingAgent(),
        dg=dg,
        tariffs=TariffIntake(client, settings),
        attachments=AttachmentReader(client),
        review_dir=settings.db_path.parent / "review",
        bids=AirlineBidSource(
            directory, sender, portal_source.portal.ports, rate_desk=settings.rate_desk_address
        ),
    )


def stop_file(settings: Settings) -> Path:
    return settings.db_path.parent / "STOP"


async def poll_loop(orchestrator: Orchestrator, interval_s: float, stop: asyncio.Event) -> None:
    while not stop.is_set():
        if stop_file(orchestrator.settings).exists():
            log.info("stop_file_found")
            stop.set()
            break
        try:
            await orchestrator.poll_once()
        except Exception:
            log.exception("poll_failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_s)


def reprocess_ids() -> list[int]:
    raw = os.environ.get("REPROCESS_MAIL_IDS", "")
    return [int(part) for part in raw.split(",") if part.strip().isdigit()]


async def reprocess(orchestrator: Orchestrator) -> None:
    for mail_id in reprocess_ids():
        try:
            mail = await orchestrator.mailbox.read_one(mail_id)
        except Exception:
            log.exception("reprocess_read_failed", extra={"mail": mail_id})
            continue
        if orchestrator.store.outbox_status(mail.thread_root_id, Stage.QUOTED) is not None:
            log.info("reprocess_skipped_already_quoted", extra={"mail": mail_id})
            continue
        if is_stale(mail.received_at, datetime.now(UTC), orchestrator.settings.rfq_lifetime_s):
            log.info("reprocess_skipped_stale", extra={"mail": mail_id})
            continue
        log.info("reprocess_started", extra={"mail": mail_id})
        task = asyncio.create_task(orchestrator.handle_rfq(mail), name=f"rfq-{mail_id}")
        orchestrator.tasks.add(task)
        task.add_done_callback(orchestrator.tasks.discard)


async def run_once(settings: Settings, stop: asyncio.Event) -> None:
    try:
        seeded = seed_live_store(live_store())
        if seeded:
            log.info("tariffs_seeded", extra={"added": seeded})
    except Exception:
        log.exception("tariff_seed_failed")
    store = Store(settings.db_path)
    try:
        async with httpx.AsyncClient(
            base_url=settings.base_url, headers=auth_headers(settings), timeout=15
        ) as client:
            orchestrator = build(settings, client, store)
            log.info(
                "bot_started",
                extra={
                    "dry_run": settings.dry_run,
                    "kill_switch": settings.kill_switch,
                    "model": settings.llm_model,
                    "cursor": store.get_cursor(),
                },
            )
            backfill = getattr(orchestrator.pickup, "backfill", None)
            if callable(backfill):
                try:
                    await backfill(client, settings.base_url)
                except Exception:
                    log.exception("pickup_backfill_failed")
            if orchestrator.booker is not None:
                try:
                    await orchestrator.booker.recover(orchestrator)
                except Exception:
                    log.exception("booking_recover_failed")
            sender = asyncio.create_task(orchestrator.sender_worker(), name="sender")
            await reprocess(orchestrator)
            try:
                await poll_loop(orchestrator, settings.poll_interval_s, stop)
                await asyncio.wait_for(orchestrator.outbox.join(), timeout=10)
            finally:
                sender.cancel()
                for task in list(orchestrator.tasks):
                    task.cancel()
    finally:
        store.close()


async def supervise() -> None:
    settings = load_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(signum, stop.set)
    delay = 1.0
    while not stop.is_set():
        try:
            await run_once(settings, stop)
            delay = 1.0
        except Exception:
            log.exception("bot_crashed_restarting", extra={"delay_s": delay})
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)
            delay = min(delay * 2, 30.0)
    log.info("bot_stopped")


def main() -> int:
    configure_logging()
    try:
        lock = single_instance(load_settings().db_path.with_name("bot.lock"))
    except AlreadyRunning as error:
        log.error("bot_already_running", extra={"detail": str(error)})
        return 1
    try:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(supervise())
    finally:
        lock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
