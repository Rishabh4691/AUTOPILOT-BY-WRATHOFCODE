import json
import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from core.contracts import Event, Mail, MailKind, Stage

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"

STORE_TABLES = """
CREATE TABLE IF NOT EXISTS cursor (
  name  TEXT PRIMARY KEY,
  value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS seen_messages (
  id             INTEGER PRIMARY KEY,
  kind           TEXT NOT NULL,
  thread_root_id INTEGER NOT NULL,
  received_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rfq_threads (
  thread_root_id INTEGER PRIMARY KEY,
  rfq_mail_id    INTEGER NOT NULL,
  customer       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
  thread_id       INTEGER NOT NULL,
  stage           TEXT NOT NULL,
  mail_id         INTEGER NOT NULL,
  status          TEXT NOT NULL,
  created_at      TEXT NOT NULL,
  sent_message_id INTEGER,
  reason          TEXT,
  UNIQUE(thread_id, stage)
);
"""

RFQ_COLUMNS = (
    "status",
    "preference",
    "origin",
    "destination",
    "chargeable_kg",
    "carrier",
    "total",
    "currency",
    "rate_id",
    "quoted_at",
    "email_body",
    "breakdown_json",
    "human_takeover",
)
UPDATE_RFQ_SQL = """
UPDATE rfqs SET
  status = CASE WHEN :set_status THEN :status ELSE status END,
  preference = CASE WHEN :set_preference THEN :preference ELSE preference END,
  origin = CASE WHEN :set_origin THEN :origin ELSE origin END,
  destination = CASE WHEN :set_destination THEN :destination ELSE destination END,
  chargeable_kg = CASE WHEN :set_chargeable_kg THEN :chargeable_kg ELSE chargeable_kg END,
  carrier = CASE WHEN :set_carrier THEN :carrier ELSE carrier END,
  total = CASE WHEN :set_total THEN :total ELSE total END,
  currency = CASE WHEN :set_currency THEN :currency ELSE currency END,
  rate_id = CASE WHEN :set_rate_id THEN :rate_id ELSE rate_id END,
  quoted_at = CASE WHEN :set_quoted_at THEN :quoted_at ELSE quoted_at END,
  email_body = CASE WHEN :set_email_body THEN :email_body ELSE email_body END,
  breakdown_json = CASE WHEN :set_breakdown_json THEN :breakdown_json ELSE breakdown_json END,
  human_takeover = CASE WHEN :set_human_takeover THEN :human_takeover ELSE human_takeover END
WHERE id = :rfq_id
"""

SqlValue = str | int | float | None

logger = logging.getLogger(__name__)


def _sql_value(value: object) -> SqlValue:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bool):
        return int(value)
    if value is None or isinstance(value, str | int | float):
        return value
    return str(value)


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._conn.executescript(STORE_TABLES)

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _scalar(self, sql: str, params: tuple[SqlValue, ...]) -> SqlValue:
        row = self._conn.execute(sql, params).fetchone()
        return None if row is None else row[0]

    def get_cursor(self, name: str = "mailbox") -> int:
        value = self._scalar("SELECT value FROM cursor WHERE name = ?", (name,))
        return int(value) if value is not None else 0

    def set_cursor(self, value: int, name: str = "mailbox") -> None:
        with self._write() as conn:
            conn.execute(
                "INSERT INTO cursor(name, value) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET value = MAX(value, excluded.value)",
                (name, value),
            )

    def mark_seen(self, mail: Mail, kind: MailKind) -> bool:
        with self._write() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO seen_messages(id, kind, thread_root_id, received_at) "
                "VALUES (?, ?, ?, ?)",
                (mail.id, kind.value, mail.thread_root_id, mail.received_at.isoformat()),
            )
            return cursor.rowcount == 1

    def is_seen(self, mail_id: int) -> bool:
        return self._scalar("SELECT 1 FROM seen_messages WHERE id = ?", (mail_id,)) is not None

    def register_rfq_thread(self, thread_root_id: int, rfq_mail_id: int, customer: str) -> bool:
        with self._write() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO rfq_threads(thread_root_id, rfq_mail_id, customer) "
                "VALUES (?, ?, ?)",
                (thread_root_id, rfq_mail_id, customer),
            )
            return cursor.rowcount == 1

    def known_rfq_threads(self) -> frozenset[int]:
        rows = self._conn.execute("SELECT thread_root_id FROM rfq_threads").fetchall()
        return frozenset(int(row[0]) for row in rows)

    def rfq_thread_customer(self, thread_root_id: int) -> str | None:
        value = self._scalar(
            "SELECT customer FROM rfq_threads WHERE thread_root_id = ?", (thread_root_id,)
        )
        return None if value is None else str(value)

    def claim_outbox(self, thread_id: int, stage: Stage, mail_id: int, now: datetime) -> bool:
        with self._write() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO outbox(thread_id, stage, mail_id, status, created_at) "
                "VALUES (?, ?, ?, 'claimed', ?)",
                (thread_id, stage.value, mail_id, now.isoformat()),
            )
            return cursor.rowcount == 1

    def mark_outbox_sent(self, thread_id: int, stage: Stage, sent_message_id: int) -> None:
        with self._write() as conn:
            conn.execute(
                "UPDATE outbox SET status = 'sent', sent_message_id = ? "
                "WHERE thread_id = ? AND stage = ?",
                (sent_message_id, thread_id, stage.value),
            )

    def mark_outbox_failed(self, thread_id: int, stage: Stage, reason: str) -> None:
        with self._write() as conn:
            conn.execute(
                "UPDATE outbox SET status = 'failed', reason = ? WHERE thread_id = ? AND stage = ?",
                (reason, thread_id, stage.value),
            )

    def outbox_status(self, thread_id: int, stage: Stage) -> str | None:
        value = self._scalar(
            "SELECT status FROM outbox WHERE thread_id = ? AND stage = ?",
            (thread_id, stage.value),
        )
        return None if value is None else str(value)

    def upsert_rfq(
        self,
        rfq_id: str,
        thread_id: str,
        customer: str,
        subject: str,
        received_at: datetime,
        status: str,
    ) -> None:
        with self._write() as conn:
            conn.execute(
                "INSERT INTO rfqs(id, thread_id, customer, subject, received_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "thread_id = excluded.thread_id, customer = excluded.customer, "
                "subject = excluded.subject, received_at = excluded.received_at, "
                "status = excluded.status",
                (rfq_id, thread_id, customer, subject, received_at.timestamp(), status),
            )

    def update_rfq(self, rfq_id: str, **fields: object) -> None:
        unknown = sorted(set(fields) - set(RFQ_COLUMNS))
        if unknown:
            raise ValueError(f"unknown rfqs columns: {', '.join(unknown)}")
        params: dict[str, SqlValue] = {"rfq_id": rfq_id}
        for name in RFQ_COLUMNS:
            params[f"set_{name}"] = int(name in fields)
            params[name] = _sql_value(fields.get(name))
        with self._write() as conn:
            conn.execute(UPDATE_RFQ_SQL, params)

    def insert_event(self, event: Event) -> None:
        with self._write() as conn:
            conn.execute(
                "INSERT INTO events(ts, agent, rfq_id, step, status, message, duration_ms, "
                "llm_cost_usd, data_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.ts.timestamp(),
                    event.agent.value,
                    event.rfq_id,
                    event.step,
                    event.status.value,
                    event.message,
                    event.duration_ms,
                    float(event.llm_cost_usd),
                    json.dumps(event.data),
                ),
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class SqliteEventSink:
    def __init__(self, store: Store) -> None:
        self._store = store

    def emit(self, event: Event) -> None:
        self._store.insert_event(event)
        logger.info(
            "%s %s %s: %s",
            event.agent.value,
            event.step,
            event.status.value,
            event.message,
        )
