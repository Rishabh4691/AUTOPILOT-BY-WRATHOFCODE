import time

from .db import rows

AGENTS = {
    "router": {"label": "Router", "role": "Reads and sorts every email", "target_ms": 500},
    "rfq": {"label": "RFQ", "role": "Prices and quotes requests", "target_ms": 120_000},
    "booking": {"label": "Booking", "role": "Books accepted quotes", "target_ms": 5_000},
    "tracking": {"label": "Tracking", "role": "Answers shipment questions", "target_ms": 3_000},
    "tariff": {"label": "Tariff", "role": "Loads new rate sheets", "target_ms": 10_000},
}
MAX_COST_PER_TASK = 0.10
DONE = ("ok", "fail")


def score(success, avg_ms, cost_per_task, target_ms):
    speed = 1.0 if not avg_ms else min(1.0, target_ms / avg_ms)
    cheap = max(0.0, 1 - cost_per_task / MAX_COST_PER_TASK)
    return round(100 * (0.5 * success + 0.3 * speed + 0.2 * cheap))


def light(last, recent_fails, now):
    if last is None:
        return "off"
    if recent_fails:
        return "red"
    if last["status"] == "start" and now - last["ts"] < 360:
        return "busy"
    return "green" if now - last["ts"] < 900 else "idle"


def agent_cards(db):
    now = time.time()
    totals = {
        r["agent"]: r
        for r in rows(
            db,
            """SELECT agent,
                      SUM(status='ok') AS ok,
                      SUM(status='fail') AS fail,
                      AVG(CASE WHEN status IN ('ok','fail') THEN duration_ms END) AS avg_ms,
                      SUM(llm_cost_usd) AS cost,
                      SUM(status='fail' AND ts > ?) AS recent_fails
               FROM events GROUP BY agent""",
            now - 900,
        )
    }
    cards = []
    for key, meta in AGENTS.items():
        t = totals.get(key, {})
        ok, fail = t.get("ok") or 0, t.get("fail") or 0
        done = ok + fail
        cost = t.get("cost") or 0.0
        success = ok / done if done else 0.0
        last = next(iter(rows(db, "SELECT * FROM events WHERE agent=? ORDER BY id DESC LIMIT 1", key)), None)
        cards.append({
            "agent": key,
            **meta,
            "light": light(last, t.get("recent_fails") or 0, now),
            "now": last["message"] if last else "Waiting for first task",
            "now_rfq": last["rfq_id"] if last else None,
            "last_ts": last["ts"] if last else None,
            "tasks_done": done,
            "success_rate": round(success, 3),
            "avg_ms": round(t["avg_ms"]) if t.get("avg_ms") else None,
            "llm_cost_usd": round(cost, 5),
            "productivity": score(success, t.get("avg_ms"), cost / done if done else 0, meta["target_ms"]) if done else None,
        })
    return cards
