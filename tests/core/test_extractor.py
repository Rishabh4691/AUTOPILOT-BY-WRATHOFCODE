import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from core.agents.extractor import ASSUMED_PREFERENCE_NOTE, RegexRfqExtractor
from core.agents.mailbox import parse_mail
from core.config import Settings, load_settings
from core.contracts import ExtractionError, LlmResult, LlmUsage, Mail, Preference

MAIL_DIR = Path(__file__).parent / "fixtures" / "mail"


class FakeLlm:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[tuple[str, str, int, bool]] = []

    async def complete(
        self, system: str, user: str, max_output_tokens: int, json_mode: bool = False
    ) -> LlmResult:
        self.calls.append((system, user, max_output_tokens, json_mode))
        return LlmResult(text=self.reply, usage=LlmUsage(model="fake", input_tokens=10))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(tmp_path, {"FIVEU_API_KEY": "test-key"})


def fixture_mail(name: str) -> Mail:
    return parse_mail(json.loads((MAIL_DIR / name).read_text(encoding="utf-8")))


def make_mail(body: str, subject: str = "Request") -> Mail:
    return Mail(
        id=7,
        sender="buyer@example.com",
        to="wrathofcode@hackloop.mail",
        subject=subject,
        body=body,
        in_reply_to=None,
        references=(),
        received_at=datetime(2026, 11, 21, 14, 0, tzinfo=UTC),
    )


async def test_english_kg_and_cm(settings: Settings) -> None:
    rfq, usage = await RegexRfqExtractor(settings, None).extract(fixture_mail("rfq_english.json"))
    assert usage is None
    assert (rfq.origin, rfq.destination) == ("FRA", "ORD")
    assert rfq.gross_kg == Decimal("350")
    assert rfq.pieces[0].count == 2
    assert rfq.pieces[0].length_cm == Decimal("120")
    assert rfq.door_pickup is True
    assert rfq.pickup_zone == "60"
    assert rfq.preference == Preference.FASTEST
    assert rfq.preference_assumed is False
    assert rfq.customer == "buyer@example.com"
    assert rfq.thread_root_id == 101


async def test_pounds_and_inches(settings: Settings) -> None:
    body = "Please quote JFK-LHR, 3 pieces of 48x40x40 in, weight: 770 lbs, cheapest please"
    rfq, _ = await RegexRfqExtractor(settings, None).extract(make_mail(body))
    assert (rfq.origin, rfq.destination) == ("JFK", "LHR")
    assert rfq.gross_kg == Decimal("349.27")
    assert rfq.pieces[0].count == 3
    assert rfq.pieces[0].length_cm == Decimal("121.92")
    assert rfq.door_pickup is False
    assert rfq.preference == Preference.CHEAPEST


async def test_comma_decimals_and_thousands(settings: Settings) -> None:
    body = "Origin: FRA\nDestination: SIN\nGross weight 1.250 kg\nTotal 12,5 cbm\nin USD"
    rfq, _ = await RegexRfqExtractor(settings, None).extract(make_mail(body))
    assert rfq.gross_kg == Decimal("1250")
    assert rfq.volume_cbm == Decimal("12.5")
    assert rfq.currency == "USD"


async def test_multi_piece_weights_are_summed(settings: Settings) -> None:
    body = (
        "FRA -> NRT\n2 pcs 120 x 80 x 100 cm 150 kg each\n1 x 60x40x40 cm 20 kg\nready 2026-12-01"
    )
    rfq, _ = await RegexRfqExtractor(settings, None).extract(make_mail(body))
    assert len(rfq.pieces) == 2
    assert rfq.gross_kg == Decimal("320")
    assert rfq.ready_date == date(2026, 12, 1)


async def test_german_html_body(settings: Settings) -> None:
    mail = fixture_mail("rfq_german_html.json")
    rfq, _ = await RegexRfqExtractor(settings, None).extract(mail)
    assert (rfq.origin, rfq.destination) == ("MUC", "SIN")
    assert rfq.pieces[0].count == 3
    assert rfq.gross_kg == Decimal("37.5")
    assert rfq.door_pickup is True
    assert rfq.pickup_zone == "80"
    assert rfq.preference == Preference.CHEAPEST
    assert rfq.preference_assumed is False
    assert rfq.currency == "EUR"
    assert rfq.ready_date == date(2026, 12, 1)


async def test_unknown_preference_assumes_cheapest(settings: Settings) -> None:
    rfq, _ = await RegexRfqExtractor(settings, None).extract(make_mail("FRA to ORD, 100 kg"))
    assert rfq.preference == Preference.CHEAPEST
    assert rfq.preference_assumed is True
    assert ASSUMED_PREFERENCE_NOTE in rfq.notes


async def test_missing_route_uses_one_llm_call(settings: Settings) -> None:
    llm = FakeLlm(json.dumps({"origin": "fra", "destination": "ORD", "gross_kg": None}))
    rfq, usage = await RegexRfqExtractor(settings, llm).extract(
        make_mail("Ship 200 kg from Frankfurt to Chicago")
    )
    assert len(llm.calls) == 1
    assert llm.calls[0][2] == 300
    assert llm.calls[0][3] is True
    assert (rfq.origin, rfq.destination) == ("FRA", "ORD")
    assert rfq.gross_kg == Decimal("200")
    assert usage is not None and usage.model == "fake"


async def test_bad_llm_reply_is_extraction_error(settings: Settings) -> None:
    llm = FakeLlm("not json at all")
    with pytest.raises(ExtractionError):
        await RegexRfqExtractor(settings, llm).extract(make_mail("Ship 200 kg to Chicago"))


async def test_missing_route_without_llm_fails(settings: Settings) -> None:
    with pytest.raises(ExtractionError, match="origin"):
        await RegexRfqExtractor(settings, None).extract(make_mail("Ship 200 kg somewhere"))


async def test_huge_body_is_truncated_before_llm(settings: Settings) -> None:
    llm = FakeLlm(json.dumps({"origin": "FRA", "destination": "ORD", "gross_kg": 10}))
    body = "Please ship this. " + "lorem ipsum " * 5000
    await RegexRfqExtractor(settings, llm).extract(make_mail(body))
    limit = getattr(settings, "body_char_limit", 4000)
    assert len(llm.calls) == 1
    assert len(llm.calls[0][1]) <= limit
