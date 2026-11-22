from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from core.agents.mailbox import parse_mail
from core.agents.rules_extractor import RulesFirstExtractor
from core.contracts import RFQ, Preference, PriceOption
from mail.extract import find_deadline
from tests.core.test_orchestrator import harness

ROUND83_LIKE = (
    "Hello,\n\nCould you please quote the cheapest air freight option from STR to MEL (Melbourne, AU)? The shipment "
    "will be ready on 2026-11-26 and we will deliver it to Stuttgart airport ourselves. It must arrive in Melbourne "
    "no later than 2 December 2026.\n\nThe shipment consists of 6 pieces, gross weight 1841 kg, volume 4.63 cbm.\n\n"
    "Please send me your all-in price in EUR.\n\nThanks\nSara"
)


@pytest.mark.parametrize(
    "text,want",
    [
        (ROUND83_LIKE, date(2026, 12, 2)),
        ("It must arrive no later than 2026-12-02.", date(2026, 12, 2)),
        ("Die Ware muss spätestens am 02.12.2026 in Melbourne sein.", date(2026, 12, 2)),
        ("Elle doit arriver au plus tard le 2 décembre 2026.", date(2026, 12, 2)),
        ("Debe llegar a más tardar el 2 de diciembre de 2026.", date(2026, 12, 2)),
        ("Deve arrivare entro il 2 dicembre 2026.", date(2026, 12, 2)),
        ("Moet uiterlijk 2 december 2026 aankomen.", date(2026, 12, 2)),
        ("Груз должен прибыть не позднее 02.12.2026.", date(2026, 12, 2)),
        ("货物最晚 2026年12月2日 之前到达。", date(2026, 12, 2)),
        ("12月2日までに到着する必要があります。", date(2026, 12, 2)),
        ("We need it in Melbourne by December 2nd.", date(2026, 12, 2)),
        ("Please quote by Friday; the goods must arrive by 2026-12-02.", date(2026, 12, 2)),
        ("Ready on 2026-11-26. Please quote the cheapest option.", None),
        ("Please send your offer in EUR by 25 November.", None),
        ("Please reply by 2026-11-25 at the latest.", None),
    ],
)
def test_find_deadline(text, want):
    assert find_deadline(text, 2026) == want


def test_extractor_keeps_the_deadline_as_a_note():
    raw = {
        "id": 23476, "from": "lindqvist-medtech@hackloop.mail", "to": "wrathofcode@hackloop.mail",
        "subject": "Air freight quote: STR to MEL", "body": ROUND83_LIKE, "in_reply_to": None, "references": [],
        "received_at": "2026-11-21T23:18:53+00:00", "attachments": [],
    }

    class NoModel:
        async def extract(self, mail):
            raise AssertionError("rules must read it")

    rfq, _ = asyncio.run(RulesFirstExtractor(NoModel()).extract(parse_mail(raw)))
    assert "deadline: 2026-12-02" in rfq.notes


def option(carrier: str, total: str, days: int) -> PriceOption:
    return PriceOption(source="portal", carrier=carrier, total=Decimal(total), currency="EUR", transit_days=days)


def rfq(notes: tuple[str, ...], pref: Preference = Preference.CHEAPEST) -> RFQ:
    return RFQ(
        mail_id=1, thread_root_id=1, customer="c@x", subject="q", origin="STR", destination="MEL", pieces=(),
        gross_kg=Decimal("1841"), door_pickup=False, preference=pref, preference_assumed=False,
        received_at=datetime(2026, 11, 21, 23, 18, tzinfo=UTC), ready_date=date(2026, 11, 26), notes=notes,
    )


def test_cheapest_that_lands_in_time_wins(tmp_path: Path):
    h = harness(tmp_path, now=datetime(2026, 11, 21, 23, 19, tzinfo=UTC))
    options = [option("Slowcheap", "5000", 7), option("Solace", "6060", 4), option("Rocket", "7000", 2)]
    kept = h.orchestrator.meet_deadline(rfq(("deadline: 2026-12-02",)), options)
    assert [o.carrier for o in kept] == ["Solace", "Rocket"]
    assert min(kept, key=lambda o: o.total).carrier == "Solace"


def test_no_deadline_keeps_every_option(tmp_path: Path):
    h = harness(tmp_path, now=datetime(2026, 11, 21, 23, 19, tzinfo=UTC))
    options = [option("Slowcheap", "5000", 7), option("Solace", "6060", 4)]
    assert h.orchestrator.meet_deadline(rfq(()), options) == options


def test_nobody_in_time_quotes_the_fastest_and_warns(tmp_path: Path):
    h = harness(tmp_path, now=datetime(2026, 11, 21, 23, 19, tzinfo=UTC))
    options = [option("Slowcheap", "5000", 9), option("Lessslow", "6000", 8)]
    kept = h.orchestrator.meet_deadline(rfq(("deadline: 2026-11-30",)), options)
    assert [o.carrier for o in kept] == ["Lessslow"]
    assert any(e.step == "deadline" and e.status.value == "warn" for e in h.sink.events)


def test_flight_may_leave_on_the_ready_date_round_179(tmp_path: Path):
    # Round 179 (rejected too_high): ready 27 Nov, at ORD by 29 Nov, price decides. Aurelia (2 days)
    # makes it when it leaves on the ready date; the engine had quoted only the 1-day Meridian.
    h = harness(tmp_path, now=datetime(2026, 11, 22, 9, 4, tzinfo=UTC))
    r = rfq(("deadline: 2026-11-29",)).model_copy(update={"ready_date": date(2026, 11, 27)})
    options = [option("Xenon", "782.04", 3), option("Aurelia", "929.53", 2), option("Ibisair", "1162.77", 2),
               option("Meridian", "1265.67", 1)]
    kept = h.orchestrator.meet_deadline(r, options)
    assert [o.carrier for o in kept] == ["Aurelia", "Ibisair", "Meridian"]
    assert min(kept, key=lambda o: o.total).carrier == "Aurelia"
