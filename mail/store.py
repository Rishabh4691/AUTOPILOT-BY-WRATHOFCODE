import json
import sqlite3
import time
from contextlib import contextmanager

from .config import ROOT, settings

AGENTS = ("router", "rfq", "booking", "tracking", "tariff")
_ready = set()


def init(path=None):
    path = path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    try:
        con.executescript((ROOT / "schema.sql").read_text())
        con.commit()
    finally:
        con.close()
    _ready.add(str(path))


@contextmanager
def connect(path=None):
    path = path or settings.db_path
    if str(path) not in _ready:
        init(path)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 10000")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get(key, default=None, db=None):
    if db is None:
        with connect() as db:
            return get(key, default, db)
    row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def put(key, value, db=None):
    if db is None:
        with connect() as db:
            return put(key, value, db)
    db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def log_event(agent, rfq_id, step, status, message="", duration_ms=None, llm_cost_usd=0.0, data=None, db=None):
    if db is None:
        try:
            with connect() as db:
                return log_event(agent, rfq_id, step, status, message, duration_ms, llm_cost_usd, data, db)
        except sqlite3.Error:
            return None
    db.execute(
        "INSERT INTO events (ts, agent, rfq_id, step, status, message, duration_ms, llm_cost_usd, data_json) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            time.time(),
            agent,
            rfq_id,
            step,
            status,
            (message or "")[:500],
            int(duration_ms) if duration_ms is not None else None,
            float(llm_cost_usd or 0),
            json.dumps(data, default=str) if data is not None else None,
        ),
    )


def thread_mails(thread_id, db=None):
    if db is None:
        with connect() as db:
            return thread_mails(thread_id, db)
    return [dict(r) for r in db.execute("SELECT * FROM mails WHERE thread_id=? ORDER BY id", (thread_id,))]
