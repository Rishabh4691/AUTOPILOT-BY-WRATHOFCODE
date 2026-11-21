from __future__ import annotations

import itertools
import logging
from collections.abc import Mapping
from datetime import UTC, datetime

import httpx
from pydantic import ValidationError

from core.config import Settings, auth_headers
from core.contracts import Attachment, Mail, MailboxClient, OutgoingMail
from core.http import request

log = logging.getLogger("core.agents.mailbox")

REQUIRED_FIELDS = ("id", "from", "to", "subject", "body", "received_at")
KNOWN_FIELDS = frozenset({*REQUIRED_FIELDS, "in_reply_to", "references", "attachments"})
POLL_LIMIT = 100


class MailShapeError(Exception):
    pass


class SendRejected(Exception):
    def __init__(self, status: int, text: str) -> None:
        super().__init__(f"send rejected with {status}: {text}")
        self.status = status
        self.text = text


class UnsafeRecipient(Exception):
    pass


def _attachments(raw: object) -> tuple[Attachment, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(Attachment.model_validate(item) for item in raw)


def _references(raw: object) -> tuple[int, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(int(item) for item in raw)


def parse_mail(raw: Mapping[str, object]) -> Mail:
    missing = [name for name in REQUIRED_FIELDS if raw.get(name) is None]
    if missing:
        raise MailShapeError(f"missing fields: {', '.join(missing)}")
    extra = sorted(set(raw) - KNOWN_FIELDS)
    if extra:
        log.debug("mail_unknown_fields", extra={"fields": extra})
    try:
        return Mail(
            id=int(str(raw["id"])),
            sender=str(raw["from"]).strip().lower(),
            to=str(raw["to"]).strip().lower(),
            subject=str(raw["subject"]),
            body=str(raw["body"]),
            in_reply_to=None if raw.get("in_reply_to") is None else int(str(raw["in_reply_to"])),
            references=_references(raw.get("references")),
            received_at=datetime.fromisoformat(str(raw["received_at"])),
            attachments=_attachments(raw.get("attachments")),
        )
    except (ValueError, TypeError, ValidationError) as error:
        raise MailShapeError(f"bad mail shape: {type(error).__name__}") from error


def _secrets(settings: Settings | None = None) -> list[str]:
    import os

    found = [os.getenv("FIVEU_API_KEY", ""), os.getenv("OPENAI_API_KEY", "")]
    if settings is not None:
        found.append(settings.api_key)
    return [s for s in found if s]


def _ensure_safe(mail: OutgoingMail, our_address: str | None, settings: Settings | None = None) -> None:
    from core.agents.guard import outgoing_leaks

    if our_address and mail.to.strip().lower() == our_address.strip().lower():
        raise UnsafeRecipient("refusing to send mail to our own address")
    if outgoing_leaks(mail.subject, mail.body, mail.attachments, _secrets(settings)):
        log.error("secret_blocked", extra={"to": mail.to})
        raise UnsafeRecipient("refusing to send a key or password")


class HttpMailboxClient:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings
        self.last_shape_errors: list[str] = []

    def _url(self, path: str) -> str:
        return f"{self._settings.base_url}{path}"

    async def poll(self, since_id: int) -> tuple[list[Mail], int]:
        response = await request(
            self._client,
            "GET",
            self._url("/v1/mailbox/messages"),
            params={"since_id": since_id, "limit": POLL_LIMIT},
            headers=auth_headers(self._settings),
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("messages", []) if isinstance(payload, dict) else []
        self.last_shape_errors = []
        mails: list[Mail] = []
        highest = since_id
        for item in items:
            mail = self._parse_item(item)
            if mail is not None:
                mails.append(mail)
                highest = max(highest, mail.id)
        next_since_id = payload.get("next_since_id") if isinstance(payload, dict) else None
        return mails, next_since_id if isinstance(next_since_id, int) else highest

    def _parse_item(self, item: object) -> Mail | None:
        item_id = item.get("id") if isinstance(item, dict) else None
        try:
            if not isinstance(item, dict):
                raise MailShapeError("message is not an object")
            return parse_mail(item)
        except MailShapeError as error:
            log.warning("mail_shape_error", extra={"mail_id": item_id})
            self.last_shape_errors.append(f"message {item_id}: {error}")
            return None

    async def send(self, mail: OutgoingMail) -> Mail:
        _ensure_safe(mail, self._settings.our_address, self._settings)
        response = await request(
            self._client,
            "POST",
            self._url("/v1/mailbox/messages"),
            json=mail.model_dump(exclude=set() if mail.attachments else {"attachments"}),
            headers=auth_headers(self._settings),
        )
        if 400 <= response.status_code < 500:
            raise SendRejected(response.status_code, response.text[:200])
        response.raise_for_status()
        return parse_mail(response.json())

    async def read_one(self, message_id: int) -> Mail:
        response = await request(
            self._client,
            "GET",
            self._url(f"/v1/mailbox/messages/{message_id}"),
            headers=auth_headers(self._settings),
        )
        response.raise_for_status()
        return parse_mail(response.json())


class DryRunMailbox:
    def __init__(self, inner: MailboxClient, our_address: str | None = None) -> None:
        self._inner = inner
        self._our_address = our_address
        self._ids = itertools.count(1)
        self.outbox: list[OutgoingMail] = []

    async def poll(self, since_id: int) -> tuple[list[Mail], int]:
        return await self._inner.poll(since_id)

    async def read_one(self, message_id: int) -> Mail:
        return await self._inner.read_one(message_id)

    async def send(self, mail: OutgoingMail) -> Mail:
        _ensure_safe(mail, self._our_address)
        log.info(
            "dry_run_send",
            extra={
                "to": mail.to,
                "subject": mail.subject,
                "in_reply_to": mail.in_reply_to,
                "body_length": len(mail.body),
            },
        )
        self.outbox.append(mail)
        return Mail(
            id=-next(self._ids),
            sender=self._our_address or "dry-run@localhost",
            to=mail.to.strip().lower(),
            subject=mail.subject,
            body=mail.body,
            in_reply_to=mail.in_reply_to,
            references=(mail.in_reply_to,),
            received_at=datetime.now(UTC),
        )
