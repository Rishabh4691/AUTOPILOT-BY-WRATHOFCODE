import asyncio
import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import db as store
from .stats import agent_cards, summary

WINDOW_S = 360


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
