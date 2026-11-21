import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKE = os.getenv("FAKE_DATA") == "1"
DB_PATH = Path(os.getenv("DB_PATH") or ROOT / ("fake.db" if FAKE else "app.db"))


def init():
    with connect() as db:
        db.executescript((ROOT / "schema.sql").read_text())


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()


def rows(db, sql, *args):
    return [dict(r) for r in db.execute(sql, args).fetchall()]
