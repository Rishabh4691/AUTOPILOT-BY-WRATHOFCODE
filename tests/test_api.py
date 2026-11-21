import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from api import db as store
from api import main
from api.stats import light, score


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(store, "FAKE", False)
    with TestClient(main.app) as c:
        yield c


def add_rfq(rid="RFQ-1", status="SOURCING", age=10, **extra):
    now = time.time()
    with store.connect() as db:
        db.execute(
            "INSERT INTO rfqs (id, customer, received_at, status, origin, destination, breakdown_json) VALUES (?,?,?,?,?,?,?)",
            (rid, "Test GmbH", now - age, status, "MUC", "JFK", extra.get("breakdown")),
        )


def add_event(agent, status, rfq_id=None, ms=None, cost=0.0, ts=None):
    with store.connect() as db:
        db.execute(
            "INSERT INTO events (ts, agent, rfq_id, step, status, message, duration_ms, llm_cost_usd) VALUES (?,?,?,?,?,?,?,?)",
            (ts or time.time(), agent, rfq_id, "step", status, f"{agent} {status}", ms, cost),
        )


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_empty_db_has_all_agents(client):
    cards = client.get("/api/agents").json()
    assert [c["agent"] for c in cards] == ["router", "rfq", "booking", "tracking", "tariff"]
    assert all(c["light"] == "off" and c["productivity"] is None for c in cards)


def test_agent_stats(client):
    add_event("rfq", "ok", ms=60_000, cost=0.0002)
    add_event("rfq", "fail", ms=180_000)
    card = next(c for c in client.get("/api/agents").json() if c["agent"] == "rfq")
    assert card["tasks_done"] == 2
    assert card["success_rate"] == 0.5
    assert card["avg_ms"] == 120_000
    assert card["light"] == "red"


def test_status_aliases_count(client):
    add_event("tracking", "success")
    add_event("tracking", "ERROR")
    card = next(c for c in client.get("/api/agents").json() if c["agent"] == "tracking")
    assert card["tasks_done"] == 2


def test_unknown_agent_is_shown_not_rejected(client):
    add_event("watcher", "ok")
    assert "watcher" in [c["agent"] for c in client.get("/api/agents").json()]


def test_rfq_list_and_detail(client):
    add_rfq(breakdown=json.dumps({"lines": [], "total": 100, "currency": "EUR"}))
    add_event("rfq", "start", rfq_id="RFQ-1")
    r = client.get("/api/rfqs").json()[0]
    assert r["deadline"] == pytest.approx(r["received_at"] + 360)
    detail = client.get("/api/rfqs/RFQ-1").json()
    assert detail["breakdown"]["total"] == 100
    assert len(detail["events"]) == 1


def test_bad_breakdown_json_does_not_crash(client):
    add_rfq(breakdown="{not json")
    assert client.get("/api/rfqs/RFQ-1").json()["breakdown"] is None


def test_missing_rfq_is_404(client):
    assert client.get("/api/rfqs/nope").status_code == 404
    assert client.post("/api/rfqs/nope/takeover", json={"on": True}).status_code == 404


def test_takeover_and_hand_back(client):
    add_rfq()
    assert client.post("/api/rfqs/RFQ-1/takeover", json={"on": True, "by": "Aditi"}).json()["human_takeover"]
    detail = client.get("/api/rfqs/RFQ-1").json()
    assert detail["human_takeover"] is True
    assert detail["events"][-1]["message"] == "Aditi took the controls"
    client.post("/api/rfqs/RFQ-1/takeover", json={"on": False, "by": "Aditi"})
    assert client.get("/api/rfqs/RFQ-1").json()["human_takeover"] is False


def test_summary(client):
    add_rfq("A", "QUOTED")
    add_rfq("B", "FAILED")
    with store.connect() as db:
        db.execute("UPDATE rfqs SET quoted_at = received_at + 90 WHERE id='A'")
    add_event("rfq", "ok", cost=0.0004)
    s = client.get("/api/summary").json()
    assert (s["rfqs"], s["quoted"], s["failed"], s["under_2min"]) == (2, 1, 1, 1)
    assert s["median_s"] == 90
    assert s["llm_per_quote"] == pytest.approx(0.0004)


def test_init_adds_missing_columns(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE rfqs (id TEXT PRIMARY KEY, received_at REAL, status TEXT)")
    con.commit()
    con.close()
    monkeypatch.setattr(store, "DB_PATH", path)
    store.init()
    with store.connect() as db:
        assert "human_takeover" in store.columns(db, "rfqs")


def test_score_weights():
    assert score(1.0, 60_000, 0.0, 120_000) == 100
    assert score(0.0, None, 0.0, 120_000) == 50
    assert score(1.0, 240_000, 0.10, 120_000) == 65


def test_light():
    now = time.time()
    assert light(None, None, now) == "off"
    assert light({"status": "start", "ts": now}, None, now) == "busy"
    assert light({"status": "ok", "ts": now}, {"status": "ok", "ts": now}, now) == "green"
    assert light({"status": "ok", "ts": now}, {"status": "fail", "ts": now}, now) == "red"
    assert light({"status": "ok", "ts": now - 2000}, {"status": "ok", "ts": now - 2000}, now) == "idle"
