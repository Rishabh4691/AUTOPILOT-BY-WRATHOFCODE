import asyncio
import dataclasses
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from core.agents.mailbox import DryRunMailbox, parse_mail
from core.config import Settings, auth_headers, load_settings
from core.contracts import Mail
from core.main import build, configure_logging
from core.store import Store


def prepare(fixture: Path) -> tuple[Settings, Mail]:
    settings = dataclasses.replace(
        load_settings(), dry_run=True, db_path=Path("data/replay.db").resolve()
    )
    for suffix in ("", "-wal", "-shm"):
        Path(f"{settings.db_path}{suffix}").unlink(missing_ok=True)
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    raw["received_at"] = datetime.now(UTC).isoformat()
    return settings, parse_mail(raw)


async def replay(settings: Settings, mail: Mail) -> int:
    store = Store(settings.db_path)
    try:
        async with httpx.AsyncClient(
            base_url=settings.base_url, headers=auth_headers(settings), timeout=15
        ) as client:
            orchestrator = build(settings, client, store)
            orchestrator.route(mail)
            while orchestrator.tasks:
                await asyncio.gather(*list(orchestrator.tasks))
            while not orchestrator.outbox.empty():
                await orchestrator.send_quote(orchestrator.outbox.get_nowait())
            mailbox = orchestrator.mailbox
            outbox = mailbox.outbox if isinstance(mailbox, DryRunMailbox) else []
            for outgoing in outbox:
                print("WOULD SEND to:", outgoing.to)
                print("subject:", outgoing.subject)
                print("in_reply_to:", outgoing.in_reply_to)
                print("body:\n" + outgoing.body)
            for row in store._conn.execute(
                "select step, status, message, llm_cost_usd from events order by id"
            ):
                print("event:", tuple(row))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    configure_logging()
    sys.exit(asyncio.run(replay(*prepare(Path(sys.argv[1])))))
