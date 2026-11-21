import asyncio
import json
from decimal import Decimal
from pathlib import Path

import pytest

from core.agents.classifier import looks_like_rfq
from core.agents.mailbox import parse_mail
from core.agents.rules_extractor import RulesFirstExtractor
from core.agents.trucker import parse_hours, parse_price
from mail.files import file_text
from mail.lang import detect

HERE = Path(__file__).parent / "fixtures" / "attachments"
MAILS = {int(k): v for k, v in json.loads((HERE / "mails.json").read_text(encoding="utf-8")).items()}

CASES = [
    (64, 17573, "r64-request.docx", ("HAM", "YYZ", Decimal("827"), Decimal("2.92"), True, "20", "fastest")),
    (66, 18361, "r66-request.txt", ("DUS", "PEK", Decimal("1494"), Decimal("4.29"), True, "45", "cheapest")),
    (67, 18684, "r67-request.pdf", ("DUS", "RUH", Decimal("1728"), Decimal("6.31"), True, "40", "cheapest")),
    (75, 21129, "r75-request.pdf", ("STR", "EZE", Decimal("169"), Decimal("0.56"), True, "72", "fastest")),
    (72, 20161, None, ("CGN", "LIM", Decimal("704"), Decimal("3.08"), True, "50", "cheapest")),
    (82, 23198, None, ("HAM", "SGN", Decimal("641.0031295129"), Decimal("2.690096000"), False, None, "fastest")),
]


class NoModel:
    async def extract(self, mail):
        raise AssertionError("the rules must read this request without the model")


@pytest.mark.parametrize("round_no,mail_id,filename,want", CASES, ids=[f"round{c[0]}" for c in CASES])
def test_real_round_is_an_rfq_and_reads_right(round_no, mail_id, filename, want):
    mail = parse_mail(MAILS[mail_id])
    assert looks_like_rfq(mail), f"round {round_no} must be seen as a request"
    files = [(filename, file_text(filename, (HERE / filename).read_bytes()))] if filename else []

    async def texts(_mail):
        return files

    rfq, _ = asyncio.run(RulesFirstExtractor(NoModel(), attachments=texts).extract(mail))
    got = (rfq.origin, rfq.destination, rfq.gross_kg, rfq.volume_cbm, rfq.door_pickup, rfq.pickup_zone, rfq.preference.value)
    assert got == want
    assert not any(n == "site_unknown" for n in rfq.notes), "the postcode is in the request, no airport comparison"


def test_round72_counts_chinese_pieces_and_language():
    mail = parse_mail(MAILS[20161])

    async def none(_mail):
        return []

    rfq, _ = asyncio.run(RulesFirstExtractor(NoModel(), attachments=none).extract(mail))
    assert "pieces: 11" in rfq.notes
    assert detect(mail.body) == "zh"


@pytest.mark.parametrize(
    "filename,price,hours",
    [("r66-trucker-offer.pdf", "198.40", 33), ("r75-trucker-offer.docx", "139.73", 9)],
)
def test_trucker_offer_files_give_the_total(filename, price, hours):
    text = file_text(filename, (HERE / filename).read_bytes())
    assert str(parse_price(text)[0]) == price
    assert parse_hours(text) == hours
