import asyncio
import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import httpx
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


@app.get("/api/summary")
def stats():
    return query(summary)


@app.get("/api/rfqs")
def rfqs(limit: int = 100):
    limit = max(1, min(limit, 500))
    return query(lambda db: [shape(r) for r in store.rows(db, "SELECT * FROM rfqs ORDER BY received_at DESC LIMIT ?", limit)])


@app.get("/api/rfqs/{rfq_id}")
def rfq(rfq_id: str):
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


def shape_rounds(me: dict) -> list[dict]:
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
        rows.append({**r, "seconds": secs, "time_points": tp, "lost": lost})
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
        "rounds": shape_rounds(me),
        "bookings": me.get("bookings", []),
        "ranking": everyone.get("ranking", [])[:15],
        "overview": everyone.get("overview", {}),
        "fetched_at": _t.time(),
    }
    _board_cache.update(at=_t.time(), data=data)
    return data


_mail_index: dict = {"since": 0, "mails": [], "at": 0.0}
_round_cache: dict = {}
NOTES_PATH = store.ROOT / "data" / "round_notes.json"


def _fiveu():
    import os

    key = os.getenv("FIVEU_API_KEY")
    base = os.getenv("FIVEU_BASE_URL", "https://api.start-hack.5u.ai").rstrip("/")
    if not key:
        raise HTTPException(503, "FIVEU_API_KEY missing in .env")
    return httpx.AsyncClient(base_url=base, headers={"X-API-Key": key}, timeout=15)


async def _sync_mailbox(client) -> list[dict]:
    import time as _t

    if _t.time() - _mail_index["at"] < 5:
        return _mail_index["mails"]
    for _ in range(100):
        r = await client.get("/v1/mailbox/messages", params={"since_id": _mail_index["since"], "limit": 200})
        if r.status_code != 200:
            break
        data = r.json()
        if not data.get("messages"):
            break
        _mail_index["mails"].extend(data["messages"])
        _mail_index["since"] = data.get("next_since_id") or _mail_index["since"]
    _mail_index["at"] = _t.time()
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


async def _find_reply(client, rfq_id: int, thread: set[int]) -> dict | None:
    sem = asyncio.Semaphore(16)

    async def one(i):
        async with sem:
            r = await client.get(f"/v1/mailbox/messages/{i}")
            if r.status_code == 200:
                m = r.json()
                if m.get("from", "").startswith("wrathofcode@") and m.get("in_reply_to") in thread:
                    return m
        return None

    for start in range(rfq_id + 1, rfq_id + 600, 120):
        found = [m for m in await asyncio.gather(*(one(i) for i in range(start, start + 120))) if m]
        if found:
            return min(found, key=lambda m: m["id"])
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
        mails = await _sync_mailbox(client)
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
        reply = await _find_reply(client, rfq["id"], {rfq["id"]}) if rfq else None
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
    _round_cache[round_no] = out
    return {**out, "note": _notes().get(str(round_no), "")}


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
