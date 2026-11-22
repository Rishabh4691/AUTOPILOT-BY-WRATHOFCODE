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
    board = []

    async def fake_board():
        return board

    monkeypatch.setattr(main, "_our_verdicts", fake_board)
    bookings = []

    async def fake_bookings():
        return bookings

    monkeypatch.setattr(main, "_our_bookings", fake_bookings)
    main._test_bookings = bookings
    main._test_board = board
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


def test_summary_and_list_add_live_board_rounds(client):
    add_rfq("A", "QUOTED", age=600)
    from datetime import UTC, datetime

    sent = datetime.now(UTC).timestamp() - 60
    iso = lambda t: datetime.fromtimestamp(t, UTC).isoformat()
    main._test_board.extend(
        [
            {"round_no": 7, "sent_at": iso(sent), "answered_at": iso(sent + 30), "verdict": "accepted", "booked": True, "points": {"cost": 38.0}},
            {"round_no": 8, "sent_at": iso(sent + 5), "answered_at": None, "verdict": None, "booked": None, "points": {}},
        ]
    )
    s = client.get("/api/summary").json()
    assert s["rfqs"] == 2 and s["live_rounds"] == 2  # rounds on the 5U board
    assert s["quoted"] == 1 and s["median_s"] == 30
    assert s["llm_per_quote"] == pytest.approx(0.005)
    assert s["llm_total_usd"] == pytest.approx(0.005)
    assert s["llm_total_eur"] == pytest.approx(0.005 * s["eur_per_usd"])
    rows = client.get("/api/rfqs?limit=1000").json()
    assert [r["id"] for r in rows] == ["R8", "R7", "A"]
    assert rows[1]["status"] == "BOOKED" and rows[1]["live"] is True
    assert client.get("/api/rfqs/R7").json()["verdict"] == "accepted"


def test_shipments_take_bookings_from_the_board(client):
    from datetime import UTC, datetime

    now = datetime.now(UTC).timestamp()
    with store.connect() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS bookings (rfq_id TEXT, booking_reference TEXT, team_reference TEXT, customer TEXT, carrier TEXT, origin TEXT, destination TEXT, eta TEXT, status TEXT, note TEXT, price REAL, currency TEXT, booked_at REAL)"
        )
        required = [c[1] for c in db.execute("PRAGMA table_info(bookings)") if c[3] and c[4] is None]

        def book(**row):
            for col in required:
                row.setdefault(col, "x")
            db.execute(f"INSERT INTO bookings ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))

        book(rfq_id="RFQ-1", booking_reference="BK-1", team_reference="WOC-1", customer="Acme", carrier="Kestrel", origin="MUC", destination="SIN", status="confirmed", price=1200, currency="EUR", booked_at=now - 100)
        book(rfq_id="RFQ-2", team_reference="WOC-2", customer="Old", carrier="Orion", origin="FRA", destination="ORD", status="requested", price=900, currency="EUR", booked_at=now - 50000)
    iso = lambda t: datetime.fromtimestamp(t, UTC).isoformat()
    main._test_bookings.extend(
        [
            {"airline": "Kestrel", "booking_reference": "BK-1", "origin": "MUC", "destination": "SIN", "status": "confirmed", "booked_at": iso(now - 90)},
            {"airline": "Vega", "booking_reference": "BK-2", "origin": "HAM", "destination": "DXB", "status": "confirmed", "booked_at": iso(now - 10), "weight_kg": 120},
        ]
    )
    d = client.get("/api/shipments").json()
    rows = d["booked"] + d["delivered"]
    assert sorted(r["booking_reference"] for r in rows) == ["BK-1", "BK-2"]
    mine = next(r for r in rows if r["booking_reference"] == "BK-1")
    assert mine["customer"] == "Acme" and float(mine["price"]) == 1200


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


def test_insights_counts_lanes_airlines_and_price_pressure(client):
    now = time.time()
    with store.connect() as db:
        rows = [("A", "BOOKED", "Lumen Air Cargo"), ("B", "QUOTED", "Lumen Air Cargo"), ("C", "QUOTED", "Lumen Air Cargo")]
        for rid, status, carrier in rows:
            db.execute(
                "INSERT INTO rfqs (id, customer, received_at, quoted_at, status, origin, destination, carrier, total) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (rid, "Test GmbH", now - 100, now - 40, status, "FRA", "PEK", carrier, 4000.0),
            )
        db.execute(
            "INSERT INTO bookings (rfq_id, thread_id, team_reference, carrier, origin, destination, transit_days, status, note, booked_at) "
            "VALUES ('A','A','WOC-A','Lumen Air Cargo','FRA','PEK',3,'booked','Flight delayed by one day',?)",
            (now,),
        )
    d = client.get("/api/insights?period=day").json()
    lane = d["lanes"][0]
    assert (lane["origin"], lane["destination"], lane["requests"], lane["won"], lane["booked"]) == ("FRA", "PEK", 3, 1, 1)
    assert lane["avg_response_s"] == 60.0 and lane["top_carrier"] == "Lumen Air Cargo"
    airline = d["airlines"][0]
    assert airline["booked"] == 1 and airline["delays"] == 1 and airline["avg_transit_days"] == 3
    assert d["pressure"][0]["destination"] == "PEK"


def test_insights_without_bookings_table(client):
    assert client.get("/api/insights?period=year").json()["totals"]["booked"] == 0


def test_settings_switches_round_trip(client, tmp_path, monkeypatch):
    from core import runtime_settings

    monkeypatch.setenv("RUNTIME_SETTINGS_PATH", str(tmp_path / "settings.json"))
    runtime_settings._cache.update(mtime=None, data=dict(runtime_settings.DEFAULTS))
    assert client.get("/api/settings").json()["daily_updates"] is False
    out = client.post("/api/settings", json={"writer_model": "gpt-4.1", "daily_updates": True}).json()
    assert out["writer_model"] == "gpt-4.1" and out["daily_updates"] is True
    assert client.post("/api/settings", json={"writer_model": "gpt-9"}).status_code == 422


def test_shipments_split_booked_and_delivered(client):
    with store.connect() as db:
        for rid, eta in (("A", "2000-01-01"), ("B", "2999-01-01")):
            db.execute(
                "INSERT INTO bookings (rfq_id, thread_id, team_reference, booking_reference, carrier, eta, booked_at, status) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (rid, rid, f"WOC-{rid}", f"BK-{rid}0000000", "Lumen Air Cargo", eta, time.time(), "booked"),
            )
    d = client.get("/api/shipments").json()
    assert [r["rfq_id"] for r in d["delivered"]] == ["A"] and [r["rfq_id"] for r in d["booked"]] == ["B"]
    assert client.get("/api/claims").json() == []


def test_live_rounds_get_route_from_the_booking_made_after_them():
    from api import main
    board = [
        {"round_no": 2, "sent_at": "2026-11-22T11:00:00+00:00"},
        {"round_no": 1, "sent_at": "2026-11-22T10:50:00+00:00"},
    ]
    rows = [
        {"round_no": 2, "quoted_at": main._stamp("2026-11-22T11:00:30+00:00")},
        {"round_no": 1, "quoted_at": main._stamp("2026-11-22T10:50:20+00:00")},
    ]
    bookings = [
        {"booked_at": "2026-11-22T10:51:00+00:00", "origin": "MUC", "destination": "BKK", "airline": "Polaris", "weight_kg": 100, "booking_reference": "BK-A"},
        {"booked_at": "2026-11-22T10:51:01+00:00", "origin": "MUC", "destination": "SIN", "airline": "Aurelia", "weight_kg": 50, "booking_reference": "BK-B"},
    ]
    main._attach_bookings(rows, board, bookings)
    assert "booking_references" not in rows[0]
    assert rows[1]["destination"] == "BKK, SIN" and rows[1]["weight_kg"] == 150 and rows[1]["booking_references"] == ["BK-A", "BK-B"]
