"""Network insights: lanes, airlines and price pressure from the bot database and the 5U board."""

import re
import sqlite3
from collections import defaultdict

PERIODS = {"day": 86_400, "week": 7 * 86_400, "month": 30 * 86_400, "year": 365 * 86_400}
WON = {"ACCEPTED", "BOOKED", "TRACKING"}
QUOTED = WON | {"QUOTED"}
DELAY = re.compile(r"delay|late|postpon|rebook|verspät|retard|retras|ritard", re.I)


def _rows(db, sql, *args):
    try:
        return [dict(r) for r in db.execute(sql, args).fetchall()]
    except sqlite3.OperationalError:
        return []


def _verdicts(board_requests):
    """Our board verdict per request, keyed by its send time to the second."""
    return {str(r.get("sent_at", ""))[:19]: r for r in board_requests or []}


def _iso(ts):
    from datetime import UTC, datetime

    return datetime.fromtimestamp(float(ts), UTC).isoformat()[:19]


def insights(db, period: str = "all", now: float | None = None, board_requests=None) -> dict:
    import time

    now = now or time.time()
    since = now - PERIODS[period] if period in PERIODS else 0
    rfqs = _rows(db, "SELECT * FROM rfqs WHERE received_at >= ?", since)
    bookings = _rows(db, "SELECT * FROM bookings WHERE booked_at >= ?", since)
    verdicts = _verdicts(board_requests)

    lanes: dict = defaultdict(lambda: {"requests": 0, "quoted": 0, "won": 0, "too_high": 0, "too_low": 0,
                                        "response_s": [], "totals": [], "carriers": defaultdict(int)})
    for r in rfqs:
        o, d = (r.get("origin") or "").upper(), (r.get("destination") or "").upper()
        if not (o and d):
            continue
        lane = lanes[(o, d)]
        lane["requests"] += 1
        status = str(r.get("status") or "").upper()
        if status in QUOTED:
            lane["quoted"] += 1
            if r.get("carrier"):
                lane["carriers"][r["carrier"]] += 1
            if r.get("total"):
                lane["totals"].append(float(r["total"]))
            if r.get("quoted_at") and r.get("received_at"):
                lane["response_s"].append(float(r["quoted_at"]) - float(r["received_at"]))
        if status in WON:
            lane["won"] += 1
        verdict = verdicts.get(_iso(r["received_at"])) if r.get("received_at") else None
        if verdict and verdict.get("reason") in ("too_high", "too_low"):
            lane[verdict["reason"]] += 1

    airlines: dict = defaultdict(lambda: {"quoted": 0, "booked": 0, "transit": [], "delays": 0, "lanes": set()})
    for r in rfqs:
        if r.get("carrier") and str(r.get("status") or "").upper() in QUOTED:
            airlines[r["carrier"]]["quoted"] += 1
    for b in bookings:
        carrier = b.get("carrier")
        if not carrier:
            continue
        a = airlines[carrier]
        a["booked"] += 1
        if b.get("transit_days"):
            a["transit"].append(int(b["transit_days"]))
        if DELAY.search(f"{b.get('status') or ''} {b.get('note') or ''}"):
            a["delays"] += 1
        if b.get("origin") and b.get("destination"):
            a["lanes"].add(f"{b['origin']}-{b['destination']}")
            lane = lanes[(b["origin"].upper(), b["destination"].upper())]
            lane.setdefault("booked", 0)
            lane["booked"] = lane.get("booked", 0) + 1

    def avg(values):
        return round(sum(values) / len(values), 1) if values else None

    lane_list = []
    for (o, d), v in lanes.items():
        top = max(v["carriers"].items(), key=lambda kv: kv[1])[0] if v["carriers"] else None
        lane_list.append({
            "origin": o, "destination": d, "requests": v["requests"], "quoted": v["quoted"], "won": v["won"],
            "booked": v.get("booked", 0), "win_rate": round(v["won"] / v["quoted"], 2) if v["quoted"] else None,
            "avg_response_s": avg(v["response_s"]), "avg_total": avg(v["totals"]), "top_carrier": top,
            "too_high": v["too_high"], "too_low": v["too_low"],
        })
    lane_list.sort(key=lambda x: (-max(x["requests"], x["booked"]), x["origin"], x["destination"]))

    airline_list = [{
        "carrier": name, "quoted": a["quoted"], "booked": a["booked"],
        "acceptance": round(a["booked"] / a["quoted"], 2) if a["quoted"] else None,
        "avg_transit_days": avg(a["transit"]), "delays": a["delays"], "lanes": sorted(a["lanes"]),
    } for name, a in airlines.items()]
    airline_list.sort(key=lambda x: (-x["booked"], -x["quoted"], x["carrier"]))

    pressure = [x for x in lane_list if x["too_high"] or (x["quoted"] >= 2 and (x["win_rate"] or 0) < 0.5)]
    pressure.sort(key=lambda x: (-x["too_high"], -x["requests"]))

    return {
        "period": period if period in PERIODS else "all",
        "totals": {
            "requests": sum(x["requests"] for x in lane_list),
            "quoted": sum(x["quoted"] for x in lane_list),
            "won": sum(x["won"] for x in lane_list),
            "booked": len(bookings),
            "delays": sum(a["delays"] for a in airline_list),
            "lanes": len(lane_list),
        },
        "lanes": lane_list,
        "airlines": airline_list,
        "pressure": pressure[:10],
    }
