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
OK = ("ok", "success", "done", "sent")
FAIL = ("fail", "failed", "error", "hold")
RECENT_S = 900
BUSY_S = 360

_in = lambda vals: "(" + ",".join(f"'{v}'" for v in vals) + ")"
IS_OK = f"lower(status) IN {_in(OK)}"
IS_FAIL = f"lower(status) IN {_in(FAIL)}"
IS_DONE = f"lower(status) IN {_in(OK + FAIL)}"


def score(success, avg_ms, cost_per_task, target_ms):
    speed = 1.0 if not avg_ms else min(1.0, target_ms / avg_ms)
    cheap = max(0.0, 1 - cost_per_task / MAX_COST_PER_TASK)
    return round(100 * (0.5 * success + 0.3 * speed + 0.2 * cheap))


def light(last, last_done, now):
    if last is None:
        return "off"
    if last_done and last_done["status"].lower() in FAIL and now - last_done["ts"] < RECENT_S:
        return "red"
    if last["status"].lower() not in OK + FAIL and now - last["ts"] < BUSY_S:
        return "busy"
    return "green" if now - last["ts"] < RECENT_S else "idle"


def agent_cards(db):
    now = time.time()
    totals = {
        r["agent"]: r
        for r in rows(
            db,
            f"""SELECT agent,
                       SUM({IS_OK}) AS ok,
                       SUM({IS_FAIL}) AS fail,
                       AVG(CASE WHEN {IS_DONE} THEN duration_ms END) AS avg_ms,
                       SUM(COALESCE(llm_cost_usd, 0)) AS cost
                FROM events GROUP BY agent""",
        )
    }
    keys = list(AGENTS) + sorted(k for k in totals if k and k not in AGENTS)
    cards = []
    for key in keys:
        meta = AGENTS.get(key, {"label": key.title(), "role": "Custom agent", "target_ms": 5_000})
        t = totals.get(key, {})
        ok, fail = t.get("ok") or 0, t.get("fail") or 0
        done = ok + fail
        cost = t.get("cost") or 0.0
        success = ok / done if done else 0.0
        last = next(iter(rows(db, "SELECT * FROM events WHERE agent=? ORDER BY id DESC LIMIT 1", key)), None)
        last_done = next(iter(rows(db, f"SELECT * FROM events WHERE agent=? AND {IS_DONE} ORDER BY id DESC LIMIT 1", key)), None)
        cards.append({
            "agent": key,
            **meta,
            "light": light(last, last_done, now),
            "now": (last["message"] or last["step"]) if last else "Waiting for first task",
            "now_rfq": last["rfq_id"] if last else None,
            "last_ts": last["ts"] if last else None,
            "tasks_done": done,
            "success_rate": round(success, 3),
            "avg_ms": round(t["avg_ms"]) if t.get("avg_ms") else None,
            "llm_cost_usd": round(cost, 5),
            "productivity": score(success, t.get("avg_ms"), cost / done, meta["target_ms"]) if done else None,
        })
    return cards


def summary(db):
    r = rows(
        db,
        """SELECT COUNT(*) AS rfqs,
                  SUM(quoted_at IS NOT NULL) AS quoted,
                  SUM(upper(status) = 'FAILED') AS failed
           FROM rfqs""",
    )[0]
    times = [x["t"] for x in rows(db, "SELECT quoted_at - received_at AS t FROM rfqs WHERE quoted_at IS NOT NULL ORDER BY t")]
    cost = rows(db, "SELECT COALESCE(SUM(llm_cost_usd), 0) AS c FROM events")[0]["c"]
    booked = rows(
        db,
        "SELECT COALESCE(currency, 'EUR') AS currency, SUM(total) AS total FROM rfqs WHERE upper(status) IN ('BOOKED','TRACKING') AND total IS NOT NULL GROUP BY 1 ORDER BY 2 DESC",
    )
    quoted = r["quoted"] or 0
    return {
        "rfqs": r["rfqs"],
        "quoted": quoted,
        "failed": r["failed"] or 0,
        "median_s": round(times[len(times) // 2]) if times else None,
        "under_2min": sum(1 for t in times if t <= 120),
        "llm_per_quote": round(cost / quoted, 6) if quoted else None,
        "booked": booked,
    }
