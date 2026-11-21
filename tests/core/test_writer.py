from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.agents.writer import LlmEmailWriter, template_body, verify_body
from core.contracts import RFQ, LlmResult, LlmUsage, Piece, Preference, PriceOption
from core.llm import LlmUnavailable, TokenBudget

TOTAL = Decimal("1387.35")
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def make_rfq(door_pickup: bool = True, assumed: bool = True) -> RFQ:
    return RFQ(
        mail_id=7,
        thread_root_id=7,
        customer="buyer@example.test",
        subject="Quote please",
        origin="FRA",
        destination="ORD",
        pieces=(
            Piece(count=2, length_cm=Decimal(100), width_cm=Decimal(80), height_cm=Decimal(60)),
        ),
        gross_kg=Decimal(300),
        door_pickup=door_pickup,
        pickup_zone="60" if door_pickup else None,
        preference=Preference.CHEAPEST,
        preference_assumed=assumed,
        received_at=NOW,
    )


OPTION = PriceOption(
    source="portal", carrier="Ibisair Cargo", total=Decimal("1300"), currency="EUR", transit_days=3
)
GOOD = (
    "Hello,\nWe can fly your goods from FRA to ORD with Ibisair Cargo in 3 days.\n"
    "Our all-in price is 1387.35 EUR.\nThe rate is valid for a short time.\n"
    "WRATHOFCODE Air Freight"
)


class FakeLlm:
    def __init__(self, text: str | None) -> None:
        self.text = text
        self.calls: list[str] = []

    async def complete(
        self, system: str, user: str, max_output_tokens: int, json_mode: bool = False
    ) -> LlmResult:
        self.calls.append(user)
        if self.text is None:
            raise LlmUnavailable("down")
        return LlmResult(text=self.text, usage=LlmUsage(model="fake", input_tokens=5))


@pytest.mark.parametrize(("door", "assumed"), [(True, True), (False, False)])
def test_template_passes_verify(door: bool, assumed: bool) -> None:
    body = template_body(make_rfq(door, assumed), OPTION, TOTAL, "EUR")
    assert verify_body(body, TOTAL, "EUR") == []
    assert "Our all-in price is 1387.35 EUR." in body
    assert ("pickup from your door included" in body) is door
    assert ("assumed" in body) is assumed
    assert body.endswith("WRATHOFCODE Air Freight")


def test_template_formats_without_thousands_separator() -> None:
    body = template_body(make_rfq(), OPTION, Decimal("12345.6"), "usd")
    assert "12345.60 USD" in body
    assert verify_body(body, Decimal("12345.6"), "USD") == []


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        (GOOD.replace("1387.35", "1300.00"), "missing exact price"),
        (GOOD + "\nOr 1290.00 EUR by sea.", "other money-like amount"),
        (GOOD + "\nAbout 1500 USD.", "different currency code"),
        (GOOD + "\nIt costs $5 more with ice.", "currency symbol"),
        (GOOD + "\nDelivery is guaranteed.", "promise word"),
        (GOOD + "\nWe add free insurance.", "promise word"),
        ("   ", "empty body"),
        (GOOD + "<br>", "html tag"),
        (GOOD + "\n| a | b |", "table pipe"),
        (GOOD + "x" * 1500, "too long"),
    ],
)
def test_verify_flags_problems(body: str, problem: str) -> None:
    assert problem in verify_body(body, TOTAL, "EUR")


def test_verify_accepts_good_body() -> None:
    assert verify_body(GOOD, TOTAL, "EUR") == []


async def test_llm_body_used_with_one_call() -> None:
    llm = FakeLlm(GOOD)
    body, usage = await LlmEmailWriter(llm).write(make_rfq(), OPTION, TOTAL, "EUR")
    assert body == GOOD
    assert usage is not None and usage.model == "fake"
    assert len(llm.calls) == 1
    assert "1387.35 EUR" in llm.calls[0]


async def test_llm_failure_falls_back_to_template() -> None:
    llm = FakeLlm(None)
    rfq = make_rfq()
    body, usage = await LlmEmailWriter(llm).write(rfq, OPTION, TOTAL, "EUR")
    assert body == template_body(rfq, OPTION, TOTAL, "EUR")
    assert usage is None
    assert len(llm.calls) == 1


async def test_bad_llm_body_falls_back_but_keeps_usage() -> None:
    llm = FakeLlm(GOOD + "\nWe guarantee a discount of 10.00 EUR.")
    rfq = make_rfq()
    body, usage = await LlmEmailWriter(llm).write(rfq, OPTION, TOTAL, "EUR")
    assert body == template_body(rfq, OPTION, TOTAL, "EUR")
    assert usage is not None
    assert len(llm.calls) == 1


async def test_budget_factory_ignored_for_plain_clients() -> None:
    llm = FakeLlm(GOOD)
    writer = LlmEmailWriter(llm, budget_factory=lambda rfq: TokenBudget(10))
    body, _ = await writer.write(make_rfq(), OPTION, TOTAL, "EUR")
    assert body == GOOD
