import asyncio
import itertools
import logging
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .config import settings

log = logging.getLogger("autopilot.mail")

MAX_RETRIES = 3
_dry_ids = itertools.count(-1, -1)


class Attachment(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: int
    filename: str = ""
    content_type: str = ""
    size: int | None = None


class Mail(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    id: int
    sender: str = Field("", alias="from")
    to: str = ""
    subject: str = ""
    body: str = ""
    in_reply_to: int | None = None
    references: list[int] = []
    received_at: str = ""
    attachments: list[Attachment] = []

    @property
    def thread_id(self) -> int:
        return self.references[0] if self.references else self.id

    @property
    def sender_email(self) -> str:
        s = self.sender.strip().lower()
        if "<" in s and ">" in s:
            s = s[s.index("<") + 1 : s.index(">")]
        return s

    def received_ts(self) -> float:
        try:
            return datetime.fromisoformat(self.received_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return datetime.now(timezone.utc).timestamp()


class MailboxError(Exception):
    def __init__(self, status, detail, maybe_sent=False):
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail
        self.maybe_sent = maybe_sent


class MailClient:
    def __init__(self, http: httpx.AsyncClient | None = None):
        if not settings.api_key and http is None:
            raise RuntimeError("FIVEU_API_KEY is missing, put it in .env")
        self.http = http or httpx.AsyncClient(
            base_url=settings.base_url,
            headers={"X-API-Key": settings.api_key},
            timeout=httpx.Timeout(15, connect=5),
        )

    async def close(self):
        await self.http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def _call(self, method, url, **kw):
        safe = method == "GET"
        for attempt in range(MAX_RETRIES + 1):
            try:
                r = await self.http.request(method, url, **kw)
            except httpx.TransportError as e:
                never_arrived = isinstance(e, httpx.ConnectError)
                if not (safe or never_arrived) or attempt == MAX_RETRIES:
                    raise MailboxError(0, f"{type(e).__name__}: {e}", maybe_sent=not safe and not never_arrived) from e
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            if r.status_code == 429 or (safe and r.status_code >= 500):
                if attempt == MAX_RETRIES:
                    raise MailboxError(r.status_code, r.text[:300])
                wait = float(r.headers.get("Retry-After") or 0.5 * 2**attempt)
                log.warning("mailbox %s on %s, retry in %.1fs", r.status_code, url, wait)
                await asyncio.sleep(min(wait, 10))
                continue
            if r.status_code >= 400:
                raise MailboxError(r.status_code, r.text[:300], maybe_sent=not safe and r.status_code >= 500)
            return r
        raise MailboxError(0, "unreachable")

    async def list_messages(self, since_id: int = 0, limit: int = 200) -> tuple[list[Mail], int]:
        r = await self._call("GET", "/v1/mailbox/messages", params={"since_id": since_id, "limit": limit})
        data = r.json()
        mails = [Mail.model_validate(m) for m in data.get("messages", [])]
        next_id = data.get("next_since_id")
        if next_id is None:
            next_id = max([since_id] + [m.id for m in mails])
        return mails, int(next_id)

    async def get_message(self, message_id: int) -> Mail:
        r = await self._call("GET", f"/v1/mailbox/messages/{message_id}")
        return Mail.model_validate(r.json())

    async def download_attachment(self, message_id: int, attachment_id: int) -> bytes:
        r = await self._call("GET", f"/v1/mailbox/messages/{message_id}/attachments/{attachment_id}")
        return r.content

    async def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: int | None = None,
        attachments: list[dict] | None = None,
    ) -> dict:
        payload = {"to": to, "subject": subject, "body": body}
        if in_reply_to is not None:
            payload["in_reply_to"] = in_reply_to
        if attachments:
            payload["attachments"] = attachments
        if settings.dry_run:
            print(f"\n[DRY_RUN] to={to} in_reply_to={in_reply_to}\nSubject: {subject}\n{body}\n")
            return {**payload, "id": next(_dry_ids), "dry_run": True}
        if settings.kill_switch:
            raise MailboxError(0, "KILL_SWITCH is on, not sending")
        r = await self._call("POST", "/v1/mailbox/messages", json=payload)
        return r.json()


def reply_subject(subject: str) -> str:
    s = (subject or "").strip()
    return s if s.lower().startswith(("re:", "aw:", "sv:", "rif:", "réf:")) else f"Re: {s}".strip()
