"""Rounds 153, 158, 183: lot lines the code reads itself need no gpt-4.1 second reader."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from core.agents import crosscheck
from core.contracts import RFQ, Mail, Preference

ROUND_183 = (
    "Hi,\n\nCould you quote one all-in price in EUR for the fastest air freight option to YYZ (Toronto, CA)? "
    "The printed marketing material is ready for pickup on 2026-12-05 at our site in 21107 (Lueneburg), Germany.\n\n"
    "Lot 1: 2 cartons, each 474 kg gross (445 kg net), each 120 x 80 x 119 cm\n"
    "Lot 2: 7 drums, each 32 kg gross (28 kg net), each 110 x 110 x 103 cm\n"
    "Lot 3: 2 pallets, together 726 kg gross (646 kg net), together 4.33 cbm\n\n"
    "Please ship all lots together as a single consignment under one air waybill.\n\nMira Petersen"
)


def mail(body: str) -> Mail:
    return Mail(id=55130, sender="nordlicht-audio@hackloop.mail", to="us@x", subject="Quote", body=body,
                in_reply_to=None, references=(), received_at=datetime(2026, 11, 22, 9, 27, tzinfo=UTC))


def rfq(gross: str, cbm: str) -> RFQ:
    return RFQ(mail_id=55130, thread_root_id=55130, customer="nordlicht-audio@hackloop.mail", subject="Quote",
               origin="HAM", destination="YYZ", pieces=(), gross_kg=Decimal(gross), volume_cbm=Decimal(cbm),
               door_pickup=True, preference=Preference.FASTEST, preference_assumed=False,
               received_at=datetime(2026, 11, 22, 9, 27, tzinfo=UTC), notes=())


class Orch:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def emit(self, agent, step, status, message, rfq_id, cost=None) -> None:
        self.events.append((step, status.value, message))


async def test_lots_read_by_code_skip_the_second_reader(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("the gpt-4.1 second reader must not be asked")

    monkeypatch.setattr(crosscheck.gateway, "chat", boom)
    orch = Orch()
    await crosscheck.cross_check(orch, mail(ROUND_183), rfq("1898", "15.339"))
    assert orch.events and orch.events[0][1] == "ok" and "read by the code" in orch.events[0][2]


def test_disagreeing_extraction_still_goes_to_the_second_reader():
    assert crosscheck.lots_agree(mail(ROUND_183), rfq("1898", "15.339"))
    assert not crosscheck.lots_agree(mail(ROUND_183), rfq("2052", "6.933"))
