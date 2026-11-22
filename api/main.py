import asyncio
import json
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import db as store
from .stats import agent_cards, summary

WINDOW_S = 360
BOARD_TTL_S = 8
_board_cache: dict = {"at": 0.0, "data": None}


@asynccontextmanager
async def lifespan(app):
    store.init()
    task = None
    if store.FAKE:
        from .fake import run
        task = asyncio.create_task(run())
    yield
    if task:
        task.cancel()


app = FastAPI(title="AUTOPILOT Control Room", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def shape(r):
    r["deadline"] = r["received_at"] + WINDOW_S if r.get("received_at") else None
    try:
        r["breakdown"] = json.loads(r.pop("breakdown_json", None) or "null")
    except ValueError:
        r["breakdown"] = None
    r["human_takeover"] = bool(r.get("human_takeover"))
    return r


def query(fn):
    with store.connect() as db:
        return fn(db)


@app.get("/api/health")
def health():
    return {"ok": True, "fake": store.FAKE, "db": store.DB_PATH.name}


@app.get("/api/agents")
def agents():
    return query(agent_cards)


def _stamp(iso: str | None) -> float | None:
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso).timestamp() if iso else None
    except ValueError:
        return None


def _live_status(round_: dict) -> str:
    verdict = (round_.get("verdict") or "").lower()
    if round_.get("booked"):
        return "BOOKED"
    if verdict == "accepted":
        return "ACCEPTED"
    if verdict in ("rejected", "no answer", "no_answer", "missed"):
        return "FAILED"
    return "QUOTED" if round_.get("answered_at") else "NEW"


def _live_row(round_: dict) -> dict:
    sent = _stamp(round_.get("sent_at"))
    return {
        "id": f"R{round_['round_no']}",
        "round_no": round_["round_no"],
        "live": True,
        "customer": f"Round {round_['round_no']}",
        "origin": "—",
        "destination": "—",
        "preference": None,
        "status": _live_status(round_),
        "verdict": round_.get("verdict"),
        "reason": round_.get("reason"),
        "received_at": sent,
        "quoted_at": _stamp(round_.get("answered_at")),
        "deadline": sent + WINDOW_S if sent else None,
        "total": None,
        "currency": None,
        "human_takeover": False,
        "breakdown": None,
    }


async def _live_rounds() -> list[dict]:
    """Rounds on the 5U board that this machine's database has not seen.

    The bot that answers them may run on another laptop; the board is the shared truth.
    """
    if store.FAKE:
        return []
    board = await _our_verdicts()
    latest = query(lambda db: store.rows(db, "SELECT MAX(received_at) AS t FROM rfqs")[0]["t"])
    rows = [_live_row(r) for r in board if r.get("round_no") is not None and r.get("sent_at")]
    return [r for r in rows if r["received_at"] and (latest is None or r["received_at"] > latest + 90)]


@app.get("/api/summary")
async def stats():
    out = query(summary)
    raw = [] if store.FAKE else await _our_verdicts()
    # Model spend per quote as 5U scored it: cost points are 40 at $0 and 0 at $0.10 per quote.
    cost = [r["points"]["cost"] for r in raw if isinstance(r.get("points"), dict) and r["points"].get("cost") is not None]
    if cost:
        out["llm_per_quote"] = round(0.10 * (1 - sum(cost) / len(cost) / 40), 5)
        out["cost_points"] = round(sum(cost) / len(cost), 2)
        out["llm_total_usd"] = round(sum(0.10 * (1 - c / 40) for c in cost), 4)
        out["cost_rounds"] = len(cost)
        try:
            from sourcing.fx import get_rate

            fx = float(get_rate("USD") or 0.92)
        except Exception:
            fx = 0.92
        out["eur_per_usd"] = fx
        out["llm_per_quote_eur"] = round(out["llm_per_quote"] * fx, 5)
        out["llm_total_eur"] = round(out["llm_total_usd"] * fx, 4)
    live = await _live_rounds()
    if not live:
        return out
    # Answer times come from the board for every round: it is what 5U scored.
    board = [_live_row(r) for r in await _our_verdicts() if r.get("round_no") is not None and r.get("sent_at")]
    times = sorted(r["quoted_at"] - r["received_at"] for r in board if r["quoted_at"] and r["received_at"])
    out["rfqs"] += len(live)
    out["quoted"] = len(times)
    out["under_2min"] = sum(1 for t in times if t <= 120)
    out["failed"] += sum(1 for r in live if r["status"] == "FAILED")
    out["median_s"] = round(times[len(times) // 2]) if times else None
    out["live_rounds"] = len(live)
    return out


@app.get("/api/rfqs")
async def rfqs(limit: int = 100):
    limit = max(1, min(limit, 1000))
    local = query(lambda db: [shape(r) for r in store.rows(db, "SELECT * FROM rfqs ORDER BY received_at DESC LIMIT ?", limit)])
    merged = sorted(await _live_rounds() + local, key=lambda r: r.get("received_at") or 0, reverse=True)
    return merged[:limit]


@app.get("/api/rfqs/{rfq_id}")
async def rfq(rfq_id: str):
    if rfq_id.startswith("R") and rfq_id[1:].isdigit():
        for row in await _live_rounds():
            if row["id"] == rfq_id:
                return {**row, "events": []}
    with store.connect() as db:
        found = store.rows(db, "SELECT * FROM rfqs WHERE id=?", rfq_id)
        if not found:
            raise HTTPException(404, "RFQ not found")
        out = shape(found[0])
        out["events"] = store.rows(db, "SELECT * FROM events WHERE rfq_id=? ORDER BY id", rfq_id)
        return out


class Takeover(BaseModel):
    on: bool = True
    by: str = Field("operator", max_length=40)


@app.post("/api/rfqs/{rfq_id}/takeover")
def takeover(rfq_id: str, body: Takeover):
    who = body.by.strip() or "operator"
    with store.connect() as db:
        if not db.execute("UPDATE rfqs SET human_takeover=? WHERE id=?", (int(body.on), rfq_id)).rowcount:
            raise HTTPException(404, "RFQ not found")
        msg = f"{who} took the controls" if body.on else f"{who} handed back to autopilot"
        db.execute(
            "INSERT INTO events (ts, agent, rfq_id, step, status, message) VALUES (?,?,?,?,?,?)",
            (time.time(), "rfq", rfq_id, "takeover", "info", msg),
        )
    return {"ok": True, "human_takeover": body.on}


@app.get("/api/events")
def events(limit: int = 100):
    limit = max(1, min(limit, 1000))
    return query(lambda db: store.rows(db, "SELECT * FROM events ORDER BY id DESC LIMIT ?", limit))


def latest_id():
    return query(lambda db: db.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0])


def events_after(last):
    return query(lambda db: store.rows(db, "SELECT * FROM events WHERE id > ? ORDER BY id LIMIT 200", last))


@app.get("/api/stream")
async def stream(last_event_id: str | None = Header(None)):
    async def feed():
        last = int(last_event_id) if last_event_id and last_event_id.isdigit() else await asyncio.to_thread(latest_id)
        yield "retry: 2000\n\n"
        idle = 0
        while True:
            try:
                new = await asyncio.to_thread(events_after, last)
            except Exception:
                new = []
            for e in new:
                last = e["id"]
                yield f"id: {e['id']}\ndata: {json.dumps(e)}\n\n"
            idle = 0 if new else idle + 1
            if idle >= 15:
                idle = 0
                yield ": ping\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        feed(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _parse_ts(value):
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() if value else None


def time_points(seconds):
    if seconds is None:
        return 0.0
    if seconds <= 120:
        return 15.0
    if seconds >= 360:
        return 0.0
    return round(15 * (360 - seconds) / 240, 2)


def round_factors(everyone: dict) -> dict[int, dict]:
    """5U's few-winners multiplier per round, and a preview from the accepted count while a round is open."""
    rule = (everyone.get("rules") or {}).get("few_winners") or {}
    factors = [float(f) for f in rule.get("factors") or []]
    start = int(rule.get("from_round") or 10**9)
    out = {}
    for r in everyone.get("rounds") or []:
        n, accepted = int(r.get("round_no") or 0), int(r.get("accepted") or 0)
        official = r.get("factor")
        preview = factors[accepted - 1] if n >= start and 1 <= accepted <= len(factors) else 1.0
        out[n] = {
            "teams_accepted": accepted,
            "teams_answered": r.get("answered"),
            "factor": float(official) if official not in (None, "") else None,
            "factor_preview": preview if n >= start else None,
            "round_status": r.get("status"),
        }
    return out


def shape_rounds(me: dict, everyone: dict | None = None) -> list[dict]:
    factors = round_factors(everyone or {})
    rows = []
    for r in me.get("requests", []):
        sent, answered = _parse_ts(r.get("sent_at")), _parse_ts(r.get("answered_at"))
        secs = round(answered - sent, 1) if sent and answered else None
        verdict = r.get("verdict")
        tp = time_points(secs) if verdict == "accepted" else 0.0
        lost = []
        if verdict == "rejected":
            lost.append(f"rejected ({r.get('reason') or 'unknown'}): whole round lost")
        elif verdict in ("no answer", "open") and not answered:
            lost.append("no answer yet" if verdict == "open" else "no answer: whole round lost")
        if verdict == "accepted" and tp < 15:
            lost.append(f"slow answer ({int(secs)} s): {15 - tp:.1f} time points lost")
        if verdict == "accepted" and r.get("booked") is False:
            lost.append("accepted but not booked in time: no tracking bonus possible")
        extra = factors.get(int(r.get("round_no") or 0), {})
        mult = extra.get("factor") if extra.get("factor") is not None else extra.get("factor_preview")
        if verdict == "accepted" and mult and mult > 1:
            lost.insert(0, f"x{mult:g} few-winners bonus ({extra.get('teams_accepted')} teams accepted)")
        rows.append({**r, **extra, "seconds": secs, "time_points": tp, "lost": lost})
    return rows


@app.get("/api/board")
async def board():
    import os
    import time as _t

    if _board_cache["data"] is not None and _t.time() - _board_cache["at"] < BOARD_TTL_S:
        return _board_cache["data"]
    key = os.getenv("FIVEU_API_KEY")
    base = os.getenv("FIVEU_BASE_URL", "https://api.start-hack.5u.ai").rstrip("/")
    if not key:
        raise HTTPException(503, "FIVEU_API_KEY missing in .env")
    async with httpx.AsyncClient(base_url=base, headers={"X-API-Key": key}, timeout=10) as client:
        me_r, all_r = await asyncio.gather(client.get("/v1/board/me"), client.get("/v1/board"))
    if me_r.status_code != 200 or all_r.status_code != 200:
        raise HTTPException(502, f"5U board answered {me_r.status_code}/{all_r.status_code}")
    me, everyone = me_r.json(), all_r.json()
    data = {
        "team": me.get("team"),
        "rank": me.get("rank"),
        "total": me.get("total"),
        "scores_revealed": me.get("scores_revealed"),
        "rounds": shape_rounds(me, everyone),
        "few_winners": (everyone.get("rules") or {}).get("few_winners"),
        "bookings": me.get("bookings", []),
        "ranking": everyone.get("ranking", [])[:15],
        "overview": everyone.get("overview", {}),
        "fetched_at": _t.time(),
    }
    _board_cache.update(at=_t.time(), data=data)
    return data


_mail_index: dict = {"since": 0, "mails": [], "at": 0.0}
_mail_lock = asyncio.Lock()
_round_cache: dict = {}
NOTES_PATH = store.ROOT / "data" / "round_notes.json"


def _fiveu():
    import os

    key = os.getenv("FIVEU_API_KEY")
    base = os.getenv("FIVEU_BASE_URL", "https://api.start-hack.5u.ai").rstrip("/")
    if not key:
        raise HTTPException(503, "FIVEU_API_KEY missing in .env")
    return httpx.AsyncClient(base_url=base, headers={"X-API-Key": key}, timeout=15)


MAIL_INDEX_PATH = store.ROOT / "data" / "mail_index.json"
_sync_task: dict = {"task": None}


def _load_mail_index() -> None:
    if _mail_index["mails"]:
        return
    try:
        saved = json.loads(MAIL_INDEX_PATH.read_text())
        _mail_index["mails"] = saved.get("mails") or []
        _mail_index["since"] = int(saved.get("since") or 0)
    except (OSError, ValueError):
        pass


def _save_mail_index() -> None:
    try:
        MAIL_INDEX_PATH.write_text(json.dumps({"since": _mail_index["since"], "mails": _mail_index["mails"]}))
    except OSError:
        pass


async def _sync_pages() -> None:
    async with _mail_lock, _fiveu() as client:
        seen = {m.get("id") for m in _mail_index["mails"]}
        for _ in range(100):
            r = await client.get("/v1/mailbox/messages", params={"since_id": _mail_index["since"], "limit": 200})
            if r.status_code == 429:
                await asyncio.sleep(max(5.5, float(r.headers.get("retry-after") or 0)))
                continue
            if r.status_code != 200:
                break
            data = r.json()
            batch = data.get("messages") or []
            _mail_index["mails"].extend(m for m in batch if m.get("id") not in seen)
            seen.update(m.get("id") for m in batch)
            _mail_index["since"] = data.get("next_since_id") or _mail_index["since"]
            _save_mail_index()
            if len(batch) < 200:
                break
            await asyncio.sleep(5.5)
        _mail_index["at"] = time.time()


async def _sync_mailbox(wait_s: float = 20) -> list[dict]:
    _load_mail_index()
    task = _sync_task["task"]
    if (task is None or task.done()) and time.time() - _mail_index["at"] >= 30:
        task = _sync_task["task"] = asyncio.create_task(_sync_pages())
    if task is not None and not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_s)
        except TimeoutError:
            pass
    return _mail_index["mails"]


def _short(m: dict) -> dict:
    return {
        "id": m.get("id"),
        "at": m.get("received_at"),
        "from": m.get("from"),
        "to": m.get("to"),
        "subject": m.get("subject"),
        "body": m.get("body"),
        "attachments": [a.get("filename") for a in m.get("attachments", [])],
        "in_reply_to": m.get("in_reply_to"),
    }


def _is_reply(m: dict, thread: set[int]) -> bool:
    return (m.get("from") or "").startswith("wrathofcode@") and m.get("in_reply_to") in thread


async def _find_reply(client, rfq_id: int, thread: set[int], mails: list[dict]) -> dict | None:
    found = [m for m in mails if _is_reply(m, thread)]
    if found:
        return min(found, key=lambda m: m["id"])
    deadline = time.monotonic() + 15
    for i in range(rfq_id + 1, rfq_id + 80):
        if time.monotonic() > deadline:
            break
        r = await client.get(f"/v1/mailbox/messages/{i}")
        if r.status_code == 429:
            break
        if r.status_code == 200 and _is_reply(r.json(), thread):
            return r.json()
    return None


@app.get("/api/rounds/{round_no}")
async def round_detail(round_no: int):
    import re
    from datetime import datetime, timedelta

    async with _fiveu() as client:
        me = (await client.get("/v1/board/me")).json()
        req = next((r for r in me.get("requests", []) if r.get("round_no") == round_no), None)
        if req is None:
            raise HTTPException(404, "round not found")
        cached = _round_cache.get(round_no)
        if cached and cached["verdict"] == req.get("verdict") and req.get("verdict") not in ("open", "pending"):
            return {**cached, "note": _notes().get(str(round_no), "")}
        mails = await _sync_mailbox()
        sent = req["sent_at"][:19]
        rfq = next((m for m in mails if (m.get("received_at") or "")[:19] == sent and not m["from"].startswith("tracking@")), None)
        related, customer = [], []
        if rfq:
            rid = rfq["id"]
            for m in mails:
                if m["id"] == rid:
                    continue
                s = m.get("subject") or ""
                refs = m.get("references") or []
                if rid in refs or m.get("in_reply_to") == rid:
                    (customer if m["from"] == rfq["from"] else related).append(_short(m))
                elif re.search(rf"\b{rid}\b", s) or re.search(rf"\bref\s+{rid}\b", m.get("body") or "", re.I):
                    related.append(_short(m))
        reply = await _find_reply(client, rfq["id"], {rfq["id"]}, mails) if rfq else None
        board = (await client.get("/v1/board")).json()
        start = datetime.fromisoformat(req["sent_at"])
        window = [
            {"team": b["team"], "airline": b.get("airline")}
            for b in board.get("bookings", [])
            if start <= datetime.fromisoformat(b["booked_at"]) <= start + timedelta(minutes=6)
            and b.get("team", "").lower() != (me.get("team") or "").lower()
        ]
    out = {
        "round": round_no,
        "verdict": req.get("verdict"),
        "reason": req.get("reason"),
        "points": req.get("points"),
        "booked": req.get("booked"),
        "sent_at": req.get("sent_at"),
        "answered_at": req.get("answered_at"),
        "request": _short(rfq) if rfq else None,
        "reply": _short(reply) if reply else None,
        "customer": customer,
        "related": sorted(related, key=lambda m: m["id"])[:40],
        "others_booked": window,
    }
    if rfq and reply:
        _round_cache[round_no] = out
    loading = _sync_task["task"] is not None and not _sync_task["task"].done()
    return {**out, "note": _notes().get(str(round_no), ""), "mail_loading": loading}


def _notes() -> dict:
    try:
        return json.loads(NOTES_PATH.read_text())
    except (OSError, ValueError):
        return {}


class Note(BaseModel):
    text: str = Field("", max_length=4000)
    by: str = Field("", max_length=40)


@app.post("/api/rounds/{round_no}/note")
def save_note(round_no: int, note: Note):
    notes = _notes()
    stamp = time.strftime("%H:%M")
    notes[str(round_no)] = f"{note.text.strip()}\n(by {note.by or 'team'} at {stamp})" if note.text.strip() else ""
    NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTES_PATH.write_text(json.dumps(notes, indent=2, ensure_ascii=False))
    return {"ok": True}


_verdict_cache: dict = {"at": 0.0, "data": []}


async def _our_verdicts() -> list:
    if time.time() - _verdict_cache["at"] < 20:
        return _verdict_cache["data"]
    try:
        async with _fiveu() as client:
            _verdict_cache["data"] = (await client.get("/v1/board/me")).json().get("requests", [])
    except (HTTPException, httpx.HTTPError, ValueError):
        pass
    _verdict_cache["at"] = time.time()
    return _verdict_cache["data"]


@app.get("/api/insights")
async def network(period: str = "all"):
    from .insights import insights

    verdicts = [] if store.FAKE else await _our_verdicts()
    return query(lambda db: insights(db, period, board_requests=verdicts))


class SettingsIn(BaseModel):
    writer_model: str | None = None
    daily_updates: bool | None = None


@app.get("/api/settings")
def get_settings():
    from core import runtime_settings

    data = runtime_settings.load()
    return {**data, "models": list(runtime_settings.MODELS)}


@app.post("/api/settings")
def set_settings(body: SettingsIn):
    from core import runtime_settings

    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        data = runtime_settings.save(changes)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {**data, "models": list(runtime_settings.MODELS)}


@app.get("/api/shipments")
def shipments():
    def load(db):
        have = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "bookings" not in have:
            return {"booked": [], "delivered": []}
        updates = "shipment_updates" in have
        if updates:
            sql = (
                "SELECT b.rfq_id, b.booking_reference, b.team_reference, b.customer, b.carrier, b.origin, b.destination, b.eta, b.status, b.note, b.price, b.currency, b.booked_at, "
                "u.updates, u.last_update_at, u.delivered_at FROM bookings b "
                "LEFT JOIN shipment_updates u ON u.rfq_id = b.rfq_id ORDER BY b.booked_at DESC LIMIT 500"
            )
        else:
            sql = (
                "SELECT b.rfq_id, b.booking_reference, b.team_reference, b.customer, b.carrier, b.origin, b.destination, b.eta, b.status, b.note, b.price, b.currency, b.booked_at, "
                "0 AS updates, NULL AS last_update_at, NULL AS delivered_at FROM bookings b ORDER BY b.booked_at DESC LIMIT 500"
            )
        rows = store.rows(db, sql)
        today = time.strftime("%Y-%m-%d")
        for r in rows:
            r["delivered"] = bool(r.get("delivered_at")) or bool(r.get("eta") and str(r["eta"])[:10] <= today and r.get("booking_reference"))
        return {"booked": [r for r in rows if not r["delivered"]], "delivered": [r for r in rows if r["delivered"]]}

    return query(load)


@app.get("/api/claims")
def claims():
    def load(db):
        have = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return store.rows(db, "SELECT * FROM claims ORDER BY filed_at DESC LIMIT 200") if "claims" in have else []

    return query(load)
