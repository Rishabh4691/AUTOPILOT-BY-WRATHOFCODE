import asyncio
import fcntl
import json
import logging
import time
from typing import Awaitable, Callable

from . import store
from .client import Mail, MailboxError, MailClient
from .config import settings

log = logging.getLogger("autopilot.poller")

MAX_ATTEMPTS = 3
SINCE_KEY = "mail.since_id"
Handler = Callable[[Mail], Awaitable[None]]


class AlreadyRunning(RuntimeError):
    pass


def single_instance(path=None):
    path = path or settings.db_path.with_name("bot.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        raise AlreadyRunning(f"another bot holds {path}, stop it first")
    fh.write(str(time.time()))
    fh.flush()
    return fh


def save(db, m: Mail) -> bool:
    cur = db.execute(
        """INSERT OR IGNORE INTO mails
           (id, thread_id, sender, recipient, subject, body, in_reply_to, refs_json,
            attachments_json, received_at, received_ts, direction, stored_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?, 'in', ?)""",
        (
            m.id,
            m.thread_id,
            m.sender_email,
            m.to,
            m.subject,
            m.body,
            m.in_reply_to,
            json.dumps(m.references),
            json.dumps([a.model_dump() for a in m.attachments]),
            m.received_at,
            m.received_ts(),
            time.time(),
        ),
    )
    return cur.rowcount == 1


def from_row(row) -> Mail:
    return Mail.model_validate({
        "id": row["id"],
        "from": row["sender"],
        "to": row["recipient"] or "",
        "subject": row["subject"] or "",
        "body": row["body"] or "",
        "in_reply_to": row["in_reply_to"],
        "references": json.loads(row["refs_json"] or "[]"),
        "received_at": row["received_at"] or "",
        "attachments": json.loads(row["attachments_json"] or "[]"),
    })


async def log_only(mail: Mail):
    store.log_event("router", None, "received", "info", f"Mail {mail.id} from {mail.sender_email}: {mail.subject[:80]}")


class Poller:
    def __init__(self, client: MailClient, handler: Handler = log_only, interval: float | None = None):
        self.client = client
        self.handler = handler
        self.interval = interval or settings.poll_seconds
        self.running: dict[int, asyncio.Task] = {}
        self.thread_locks: dict[int, asyncio.Lock] = {}

    async def poll_once(self) -> list[int]:
        with store.connect() as db:
            since = int(store.get(SINCE_KEY, 0, db))
        mails, next_id = await self.client.list_messages(since)
        fresh = []
        with store.connect() as db:
            for m in mails:
                if m.sender_email == settings.our_address:
                    continue
                if save(db, m):
                    fresh.append(m.id)
            store.put(SINCE_KEY, max(next_id, since), db)
            store.put("poller.heartbeat", time.time(), db)
        if fresh:
            log.info("stored %d new mail(s): %s", len(fresh), fresh)
        for mid in fresh:
            self.dispatch(mid)
        return fresh

    def pending(self) -> list[int]:
        with store.connect() as db:
            rows = db.execute(
                "SELECT id FROM mails WHERE direction='in' AND state IN ('new','working') AND attempts < ? ORDER BY id",
                (MAX_ATTEMPTS,),
            ).fetchall()
        return [r[0] for r in rows]

    def dispatch(self, mail_id: int):
        if mail_id in self.running:
            return
        task = asyncio.create_task(self._handle(mail_id))
        self.running[mail_id] = task
        task.add_done_callback(lambda _: self.running.pop(mail_id, None))

    async def _handle(self, mail_id: int):
        with store.connect() as db:
            row = db.execute("SELECT * FROM mails WHERE id=?", (mail_id,)).fetchone()
            if row is None or row["state"] not in ("new", "working") or row["attempts"] >= MAX_ATTEMPTS:
                return
            db.execute("UPDATE mails SET state='working', attempts=attempts+1 WHERE id=?", (mail_id,))
        mail = from_row(row)
        lock = self.thread_locks.setdefault(mail.thread_id, asyncio.Lock())
        async with lock:
            try:
                await self.handler(mail)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("handler failed on mail %s", mail_id)
                with store.connect() as db:
                    tries = db.execute("SELECT attempts FROM mails WHERE id=?", (mail_id,)).fetchone()[0]
                    state = "error" if tries >= MAX_ATTEMPTS else "new"
                    db.execute("UPDATE mails SET state=?, error=? WHERE id=?", (state, f"{type(e).__name__}: {e}"[:500], mail_id))
                store.log_event("router", None, "handle", "fail", f"Mail {mail_id} failed: {type(e).__name__}: {e}"[:300])
                return
        with store.connect() as db:
            db.execute("UPDATE mails SET state='done', done_at=?, error=NULL WHERE id=? AND state='working'", (time.time(), mail_id))

    async def run(self, stop: asyncio.Event | None = None):
        stop = stop or asyncio.Event()
        for mid in self.pending():
            self.dispatch(mid)
        errors = 0
        while not stop.is_set():
            started = time.monotonic()
            try:
                await self.poll_once()
                for mid in self.pending():
                    self.dispatch(mid)
                errors = 0
            except MailboxError as e:
                errors += 1
                log.warning("poll failed (%s), %d in a row", e, errors)
                if errors in (3, 20):
                    store.log_event("router", None, "poll", "fail", f"Mailbox poll failing: {e}"[:300])
            wait = max(0.2, self.interval - (time.monotonic() - started))
            try:
                await asyncio.wait_for(stop.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
        if self.running:
            await asyncio.gather(*self.running.values(), return_exceptions=True)


async def main(handler: Handler = log_only):
    lock = single_instance()
    try:
        async with MailClient() as client:
            print(f"polling every {settings.poll_seconds}s, dry_run={settings.dry_run}, db={settings.db_path}")
            await Poller(client, handler).run()
    finally:
        lock.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(main())
    except AlreadyRunning as e:
        raise SystemExit(str(e))
    except KeyboardInterrupt:
        pass
