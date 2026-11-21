from __future__ import annotations

import logging
import time

import httpx

from core.agents.directory import CarrierDirectory
from core.config import Settings
from core.http import request

log = logging.getLogger("core.outbound")


class UnknownRecipient(Exception):
    pass


class DirectoryMailSender:
    def __init__(
        self, client: httpx.AsyncClient, settings: Settings, directory: CarrierDirectory
    ) -> None:
        self.client = client
        self.settings = settings
        self.directory = directory
        self.dry_run_log: list[tuple[str, str]] = []

    def allowed(self, address: str) -> bool:
        wanted = address.strip().lower()
        if wanted == self.settings.our_address:
            return False
        return self.directory.by_email(wanted) is not None or wanted in {
            self.settings.rate_desk_address,
            self.settings.tracking_address,
        }

    async def send_new(self, to: str, subject: str, body: str) -> int | None:
        if not self.allowed(to):
            raise UnknownRecipient(f"{to} is not in the carrier list")
        if self.settings.kill_switch:
            log.warning("kill_switch_blocked_send", extra={"to": to})
            return None
        if self.settings.dry_run:
            self.dry_run_log.append((to, subject))
            log.info("dry_run_send_new", extra={"to": to, "subject": subject, "chars": len(body)})
            return None
        response = await request(
            self.client,
            "POST",
            "/v1/mailbox/messages",
            json={"to": to, "subject": subject, "body": body},
            deadline=time.monotonic() + 20,
        )
        if response.status_code != 201:
            log.warning("send_new_rejected", extra={"to": to, "status": response.status_code})
            return None
        message_id = response.json().get("id")
        return message_id if isinstance(message_id, int) else None
