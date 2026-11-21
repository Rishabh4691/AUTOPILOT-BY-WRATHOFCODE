from __future__ import annotations

import logging
from typing import Any

import httpx

from core.config import Settings, auth_headers
from core.contracts import Agent, EventStatus, Mail, OutgoingMail, Stage
from mail import lang
from mail.dg import DgCheck, attachment_text, check, docs_request
from mail.extract import find_first_name
from mail.text import fresh_text, reply_subject

log = logging.getLogger("core.dg")


class DgGuard:
    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        agent: str = "Lena",
        company: str = "WRATHOFCODE Air Freight",
    ) -> None:
        self.client = client
        self.settings = settings
        self.agent = agent
        self.company = company
        self.cleared: set[int] = set()

    async def texts(self, mail: Mail) -> list[tuple[str, str]]:
        out = []
        for a in mail.attachments[:5]:
            try:
                r = await self.client.get(
                    f"{self.settings.base_url}/v1/mailbox/messages/{mail.id}/attachments/{a.id}",
                    headers=auth_headers(self.settings),
                    timeout=10,
                )
                if r.status_code == 200 and len(r.content) < 5_000_000:
                    out.append((a.filename, attachment_text(a.filename, r.content)))
            except httpx.HTTPError as error:
                log.warning(
                    "attachment_failed", extra={"mail": mail.id, "error": type(error).__name__}
                )
        return out

    async def inspect(self, mail: Mail) -> DgCheck:
        return check(fresh_text(mail.body), await self.texts(mail))

    async def stop_for_docs(self, orch: Any, mail: Mail) -> bool:
        if mail.id in self.cleared:
            return False
        result = await self.inspect(mail)
        if not result.dangerous:
            return False
        orch.emit(
            Agent.RFQ,
            "dangerous_goods",
            EventStatus.WARN,
            f"Request {mail.id} is dangerous goods: {'; '.join(result.reasons)[:200]}",
            mail.id,
        )
        if result.docs_attached:
            return False
        if not orch.store.claim_outbox(
            mail.thread_root_id, Stage.WAITING_DOCS, mail.id, orch.clock()
        ):
            return True
        language = lang.detect(fresh_text(mail.body) or mail.subject)
        body = docs_request(
            result,
            language,
            find_first_name(mail.sender, mail.body),
            f"WOC-{mail.id}",
            self.agent,
            self.company,
        )
        try:
            sent = await orch.mailbox.send(
                OutgoingMail(
                    to=mail.sender,
                    subject=reply_subject(mail.subject),
                    body=body,
                    in_reply_to=mail.id,
                )
            )
        except Exception as error:
            orch.store.mark_outbox_failed(
                mail.thread_root_id, Stage.WAITING_DOCS, type(error).__name__
            )
            orch.hold(
                mail.id,
                f"Dangerous goods request for {mail.id} could not be sent ({type(error).__name__}).",
            )
            return True
        orch.store.mark_outbox_sent(mail.thread_root_id, Stage.WAITING_DOCS, sent.id)
        orch.store.update_rfq(str(mail.id), status=Stage.WAITING_DOCS.value)
        orch.emit(
            Agent.RFQ,
            "docs_requested",
            EventStatus.HOLD,
            f"Asked the customer for dangerous goods documents for request {mail.id}.",
            mail.id,
        )
        return True

    async def on_reply(self, orch: Any, mail: Mail) -> bool:
        row = orch.store._conn.execute(
            "SELECT id, status FROM rfqs WHERE thread_id=? ORDER BY received_at DESC LIMIT 1",
            (str(mail.thread_root_id),),
        ).fetchone()
        if row is None or row[1] != Stage.WAITING_DOCS.value:
            return False
        rfq_id = int(row[0])
        self.cleared.add(rfq_id)
        orch.emit(
            Agent.RFQ,
            "docs_received",
            EventStatus.INFO,
            f"Customer answered the dangerous goods request for {rfq_id}. Pricing now.",
            rfq_id,
        )
        original = await orch.mailbox.read_one(rfq_id)
        await orch.handle_rfq(original)
        return True
