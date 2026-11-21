import asyncio
import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import db as store
from .stats import agent_cards

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
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


def with_deadline(r):
    r["deadline"] = r["received_at"] + WINDOW_S
    r["breakdown"] = json.loads(r.pop("breakdown_json") or "null")
    return r


@app.get("/api/health")
def health():
    return {"ok": True, "fake": store.FAKE, "db": str(store.DB_PATH.name)}


@app.get("/api/agents")
def agents():
    with store.connect() as db:
        return agent_cards(db)


@app.get("/api/rfqs")
def rfqs(limit: int = 50):
    with store.connect() as db:
        return [with_deadline(r) for r in store.rows(db, "SELECT * FROM rfqs ORDER BY received_at DESC LIMIT ?", limit)]


@app.get("/api/rfqs/{rfq_id}")
def rfq(rfq_id: str):
    with store.connect() as db:
        found = store.rows(db, "SELECT * FROM rfqs WHERE id=?", rfq_id)
        if not found:
            raise HTTPException(404, "RFQ not found")
        out = with_deadline(found[0])
        out["events"] = store.rows(db, "SELECT * FROM events WHERE rfq_id=? ORDER BY id", rfq_id)
        return out


class Takeover(BaseModel):
    on: bool = True
    by: str = "operator"


@app.post("/api/rfqs/{rfq_id}/takeover")
def takeover(rfq_id: str, body: Takeover):
    with store.connect() as db:
        if not db.execute("UPDATE rfqs SET human_takeover=? WHERE id=?", (int(body.on), rfq_id)).rowcount:
            raise HTTPException(404, "RFQ not found")
        msg = f"{body.by} took the controls" if body.on else f"{body.by} handed back to autopilot"
        db.execute(
            "INSERT INTO events (ts, agent, rfq_id, step, status, message) VALUES (?,?,?,?,?,?)",
            (time.time(), "rfq", rfq_id, "takeover", "info", msg),
        )
    return {"ok": True, "human_takeover": body.on}


@app.get("/api/events")
def events(limit: int = 100):
    with store.connect() as db:
        return store.rows(db, "SELECT * FROM events ORDER BY id DESC LIMIT ?", limit)


@app.get("/api/stream")
async def stream():
    async def feed():
        with store.connect() as db:
            last = db.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]
        yield "retry: 2000\n\n"
        while True:
            with store.connect() as db:
                new = store.rows(db, "SELECT * FROM events WHERE id > ? ORDER BY id", last)
            for e in new:
                last = e["id"]
                yield f"id: {e['id']}\ndata: {json.dumps(e)}\n\n"
            if not new:
                yield ": ping\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(feed(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
