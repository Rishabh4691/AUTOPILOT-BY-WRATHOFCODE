import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from core.contracts import Agent, Event, EventSink, EventStatus, Mail, MailKind, Stage
from core.store import SqliteEventSink, Store

NOW = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)


def make_mail(mail_id: int, references: tuple[int, ...] = ()) -> Mail:
    return Mail(
        id=mail_id,
        sender="customer@example.com",
        to="us@example.com",
        subject="RFQ",
        body="Please quote",
        in_reply_to=references[-1] if references else None,
        references=references,
        received_at=NOW,
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "nested" / "app.db"


@pytest.fixture
def store(db_path: Path) -> Iterator[Store]:
    opened = Store(db_path)
    yield opened
    opened.close()


def reopen(store: Store, db_path: Path) -> Store:
    store.close()
    return Store(db_path)


def test_cursor_persists_and_never_moves_backwards(store: Store, db_path: Path) -> None:
    assert store.get_cursor() == 0
    store.set_cursor(10)
    store.set_cursor(5)
    assert store.get_cursor() == 10
    reopened = reopen(store, db_path)
    try:
        assert reopened.get_cursor() == 10
        reopened.set_cursor(12)
        assert reopened.get_cursor() == 12
        assert reopened.get_cursor("other") == 0
    finally:
        reopened.close()


def test_mark_seen_detects_duplicates_across_restart(store: Store, db_path: Path) -> None:
    mail = make_mail(7, (3,))
    assert store.mark_seen(mail, MailKind.RFQ) is True
    assert store.mark_seen(mail, MailKind.RFQ) is False
    assert store.is_seen(7) is True
    assert store.is_seen(8) is False
    reopened = reopen(store, db_path)
    try:
        assert reopened.mark_seen(mail, MailKind.RFQ) is False
        assert reopened.is_seen(7) is True
    finally:
        reopened.close()


def test_claim_outbox_blocks_resend_across_restart(store: Store, db_path: Path) -> None:
    assert store.claim_outbox(1, Stage.QUOTED, 100, NOW) is True
    assert store.claim_outbox(1, Stage.QUOTED, 100, NOW) is False
    assert store.outbox_status(1, Stage.QUOTED) == "claimed"
    store.mark_outbox_sent(1, Stage.QUOTED, 555)
    assert store.outbox_status(1, Stage.QUOTED) == "sent"
    assert store.claim_outbox(1, Stage.BOOKED, 100, NOW) is True
    store.mark_outbox_failed(1, Stage.BOOKED, "timeout")
    assert store.outbox_status(1, Stage.BOOKED) == "failed"
    assert store.outbox_status(2, Stage.QUOTED) is None
    reopened = reopen(store, db_path)
    try:
        assert reopened.claim_outbox(1, Stage.QUOTED, 100, NOW) is False
        assert reopened.claim_outbox(1, Stage.BOOKED, 100, NOW) is False
    finally:
        reopened.close()


def test_rfq_thread_registry(store: Store) -> None:
    assert store.known_rfq_threads() == frozenset()
    assert store.register_rfq_thread(3, 3, "acme@example.com") is True
    assert store.register_rfq_thread(3, 4, "other@example.com") is False
    assert store.register_rfq_thread(9, 9, "beta@example.com") is True
    assert store.known_rfq_threads() == frozenset({3, 9})
    assert store.rfq_thread_customer(3) == "acme@example.com"
    assert store.rfq_thread_customer(42) is None


def test_rfq_rows_match_schema(store: Store, db_path: Path) -> None:
    store.upsert_rfq("rfq-1", "3", "acme@example.com", "RFQ", NOW, "NEW")
    store.update_rfq(
        "rfq-1",
        status="QUOTED",
        total=Decimal("123.45"),
        quoted_at=NOW,
        carrier="LH",
        human_takeover=False,
    )
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, thread_id, customer, subject, received_at, status, total, quoted_at, "
            "carrier, human_takeover FROM rfqs"
        ).fetchone()
    assert row == (
        "rfq-1",
        "3",
        "acme@example.com",
        "RFQ",
        NOW.timestamp(),
        "QUOTED",
        123.45,
        NOW.timestamp(),
        "LH",
        0,
    )


def test_update_rfq_rejects_unknown_column(store: Store) -> None:
    store.upsert_rfq("rfq-1", "3", "acme@example.com", "RFQ", NOW, "NEW")
    with pytest.raises(ValueError, match="bogus"):
        store.update_rfq("rfq-1", bogus=1)


def test_event_sink_writes_schema_rows(store: Store, db_path: Path) -> None:
    sink = SqliteEventSink(store)
    assert isinstance(sink, EventSink)
    sink.emit(
        Event(
            ts=NOW,
            agent=Agent.RFQ,
            step="extract",
            status=EventStatus.OK,
            message="extracted",
            rfq_id="rfq-1",
            duration_ms=42,
            llm_cost_usd=Decimal("0.0012"),
            data={"model": "gpt-5-nano", "tokens": 10},
        )
    )
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT ts, agent, rfq_id, step, status, message, duration_ms, llm_cost_usd, "
            "data_json FROM events"
        ).fetchone()
    assert row[:8] == (NOW.timestamp(), "rfq", "rfq-1", "extract", "ok", "extracted", 42, 0.0012)
    assert json.loads(row[8]) == {"model": "gpt-5-nano", "tokens": 10}


def test_journal_mode_is_wal(store: Store, db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
