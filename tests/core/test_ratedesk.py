import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import respx

from core.agents.mailbox import parse_mail
from core.agents.ratedesk import RateDeskSource
from core.contracts import RFQ, Preference
from tests.core.test_llm import SETTINGS

BASE = "https://portal.test"
REPLY = (
    'portal rates for STR-EZE, 1805.0 kg, 6.92 cbm (your mail "Rate request STR-EZE ref 4138"):\n\n'
    "- Aurelia Air Cargo (AU): 5974.55 EUR, 6 days, rate_id R-u3rSVtt9KGll6Uyr, valid until 21 Nov 2026 17:52 UTC\n"
    "- Nova Atlas Cargo (NV): 4638.85 EUR, 7 days, rate_id R-3eV_IRsAJoEV-xPr, valid until 21 Nov 2026 17:52 UTC\n"
    "- Orion Cargo Air (OR): not on the portal, email orion-cargo-air@hackloop.mail\n"
)


class Sender:
    def __init__(self):
        self.sent = []

    async def send_new(self, to, subject, body):
        self.sent.append((to, subject, body))
        return 1


def rfq():
    return RFQ(
        mail_id=4138,
        thread_root_id=4138,
        customer="sara@x",
        subject="Quote",
        origin="STR",
        destination="EZE",
        pieces=(),
        gross_kg=Decimal(1805),
        volume_cbm=Decimal("6.92"),
        door_pickup=True,
        preference=Preference.CHEAPEST,
        preference_assumed=False,
        received_at=datetime.now(UTC),
    )


@respx.mock
async def test_rate_desk_used_when_portal_is_down():
    respx.get(f"{BASE}/v1/portal/rates").respond(
        503, json={"detail": "The rate API is unavailable."}
    )
    settings = replace(SETTINGS, base_url=BASE)
    sender = Sender()
    async with httpx.AsyncClient() as client:
        src = RateDeskSource(client, settings, sender, lambda: datetime.now(UTC))
        task = asyncio.create_task(src.quote(rfq()))
        for _ in range(50):
            if sender.sent:
                break
            await asyncio.sleep(0.01)
        assert sender.sent and "ref 4138" in sender.sent[0][1]
        src.on_mail(
            parse_mail(
                {
                    "id": 9,
                    "from": settings.rate_desk_address,
                    "to": "us",
                    "subject": "Portal rates STR-EZE 1805.0 kg",
                    "body": REPLY,
                    "in_reply_to": None,
                    "references": [],
                    "received_at": datetime.now(UTC).isoformat(),
                    "attachments": [],
                }
            )
        )
        options = await task
    assert [(o.carrier, o.total, o.rate_id) for o in options] == [
        ("Aurelia Air Cargo", Decimal("5974.55"), "R-u3rSVtt9KGll6Uyr"),
        ("Nova Atlas Cargo", Decimal("4638.85"), "R-3eV_IRsAJoEV-xPr"),
    ]


@respx.mock
async def test_rate_desk_not_used_when_portal_works():
    respx.get(f"{BASE}/v1/portal/rates").respond(404, json={"detail": "unknown airline"})
    sender = Sender()
    async with httpx.AsyncClient() as client:
        src = RateDeskSource(
            client, replace(SETTINGS, base_url=BASE), sender, lambda: datetime.now(UTC)
        )
        assert await src.quote(rfq()) == []
    assert sender.sent == []
