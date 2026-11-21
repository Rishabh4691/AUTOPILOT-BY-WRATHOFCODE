import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path=ROOT / ".env"):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key, value.strip().strip("'\""))


load_env()

FAKE = os.getenv("FAKE_DATA") == "1"


def resolve_db():
    if FAKE:
        return ROOT / "data" / "fake.db"
    path = Path(os.getenv("DB_PATH") or "data/app.db")
    return path if path.is_absolute() else ROOT / path


DB_PATH = resolve_db()


NEEDED = {
    "rfqs": {
        "thread_id": "TEXT", "customer": "TEXT", "subject": "TEXT", "received_at": "REAL",
        "status": "TEXT", "preference": "TEXT", "origin": "TEXT", "destination": "TEXT",
        "chargeable_kg": "REAL", "carrier": "TEXT", "total": "REAL", "currency": "TEXT",
        "rate_id": "TEXT", "quoted_at": "REAL", "email_body": "TEXT", "breakdown_json": "TEXT",
        "human_takeover": "INTEGER NOT NULL DEFAULT 0",
    },
    "events": {
        "rfq_id": "TEXT", "message": "TEXT", "duration_ms": "INTEGER",
        "llm_cost_usd": "REAL NOT NULL DEFAULT 0", "data_json": "TEXT",
    },
}


def init():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript((ROOT / "schema.sql").read_text())
        for table, cols in NEEDED.items():
            have = columns(db, table)
            for name, kind in cols.items():
                if name not in have:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 5000")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def rows(db, sql, *args):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def columns(db, table):
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
