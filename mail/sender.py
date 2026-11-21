import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass

from . import kit, store
from .client import MailboxError, MailClient
from .config import settings

CUSTOMER_FIRST = ("quote", "tracking")


@dataclass
class Sent:
    ok: bool
    reason: str
    message_id: int | None = None


class Sender:
    def __init__(self, client: MailClient):
        self.client = client
        self.lock = asyncio.Lock()
        if not settings.dry_run:
            with store.connect() as db:
                db.execute("DELETE FROM mail_outbox WHERE state='dry_run'")

    def _is_customer(self, address: str) -> bool:
        a = address.lower()
        return a not in (settings.rate_desk, settings.tracking_desk, settings.our_address) and a not in kit.carriers()

    def _blocked(self, db, thread_id, stage, to, rfq_id) -> str | None:
        if to.lower() == settings.our_address:
            return "never mail ourselves"
        if rfq_id:
            row = db.execute("SELECT human_takeover FROM rfqs WHERE id=?", (rfq_id,)).fetchone()
            if row and row[0]:
                return "a human has the controls"
        if self._is_customer(to) and stage not in CUSTOMER_FIRST:
            quoted = db.execute(
                "SELECT 1 FROM mail_outbox WHERE thread_id=? AND stage='quote' AND state IN ('sent','dry_run','unknown')", (thread_id,)
            ).fetchone()
            if not quoted:
                return f"first reply to a customer must be the quote, not {stage}"
        return None

    async def send(self, *, thread_id: int, stage: str, to: str, subject: str, body: str,
                   in_reply_to: int | None, rfq_id: str | None = None, agent: str = "rfq") -> Sent:
        async with self.lock:
            with store.connect() as db:
                why = self._blocked(db, thread_id, stage, to, rfq_id)
                if why:
                    store.log_event(agent, rfq_id, f"send:{stage}", "info", f"Not sent: {why}", db=db)
                    return Sent(False, why)
                try:
                    db.execute(
                        "INSERT INTO mail_outbox (thread_id, stage, rfq_id, recipient, in_reply_to, subject, body, state, created_at) VALUES (?,?,?,?,?,?,?, 'sending', ?)",
                        (thread_id, stage, rfq_id, to, in_reply_to, subject, body, time.time()),
                    )
                except sqlite3.IntegrityError:
                    return Sent(False, f"already sent {stage} in thread {thread_id}")

            t0 = time.monotonic()
            try:
                out = await self.client.send_message(to, subject, body, in_reply_to=in_reply_to)
            except MailboxError as e:
                with store.connect() as db:
                    if e.maybe_sent:
                        db.execute("UPDATE mail_outbox SET state='unknown', error=? WHERE thread_id=? AND stage=?", (str(e)[:300], thread_id, stage))
                    else:
                        db.execute("DELETE FROM mail_outbox WHERE thread_id=? AND stage=?", (thread_id, stage))
                    store.log_event(agent, rfq_id, f"send:{stage}", "fail",
                                    f"Send failed{' (may have gone out, not retrying)' if e.maybe_sent else ''}: {e}"[:300],
                                    (time.monotonic() - t0) * 1000, db=db)
                return Sent(False, str(e))

            mid = out.get("id")
            state = "dry_run" if out.get("dry_run") else "sent"
            with store.connect() as db:
                db.execute(
                    "UPDATE mail_outbox SET state=?, message_id=?, sent_at=? WHERE thread_id=? AND stage=?",
                    (state, mid, time.time(), thread_id, stage),
                )
                if mid is not None:
                    db.execute(
                        """INSERT OR IGNORE INTO mails (id, thread_id, sender, recipient, subject, body, in_reply_to, refs_json,
                           attachments_json, received_at, received_ts, direction, kind, rfq_id, state, stored_at, done_at)
                           VALUES (?,?,?,?,?,?,?, '[]', '[]', ?, ?, 'out', ?, ?, 'done', ?, ?)""",
                        (mid, thread_id, settings.our_address, to, subject, body, in_reply_to,
                         out.get("received_at") or "", time.time(), stage, rfq_id, time.time(), time.time()),
                    )
                store.log_event(agent, rfq_id, f"send:{stage}", "ok",
                                f"{'Dry run' if state == 'dry_run' else 'Sent'} {stage} to {to}",
                                (time.monotonic() - t0) * 1000, data={"message_id": mid, "thread_id": thread_id}, db=db)
            return Sent(True, state, mid)

    async def reply(self, mail, stage: str, subject: str, body: str, rfq_id=None, agent="rfq") -> Sent:
        return await self.send(thread_id=mail.thread_id, stage=stage, to=mail.sender_email, subject=subject,
                               body=body, in_reply_to=mail.id, rfq_id=rfq_id, agent=agent)
