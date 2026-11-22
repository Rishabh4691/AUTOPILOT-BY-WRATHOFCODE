import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from core.contracts import PriceOption, Quote
from core.orchestrator import Orchestrator


def quote() -> Quote:
    option = PriceOption(
        source="portal", carrier="Test Air", total=Decimal("100"), currency="EUR", transit_days=2
    )
    return Quote(
        rfq_mail_id=7,
        thread_root_id=7,
        to="c@x",
        subject="Re: q",
        option=option,
        total=Decimal("100"),
        currency="EUR",
        body="Our all-in price is 100.00 EUR.",
        used_llm=False,
    )


def gate(tmp_path: Path, seconds_left: float) -> Orchestrator:
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.review_dir = tmp_path / "review"
    orchestrator.review_deadline_s = seconds_left
    orchestrator.review_context = {7: {"received_at_epoch": datetime.now(UTC).timestamp()}}
    return orchestrator


async def test_gate_is_off_without_switch_file(tmp_path: Path) -> None:
    assert await gate(tmp_path, 30).await_review(quote()) == quote()
    assert not (tmp_path / "review" / "7.json").exists()


async def test_reviewer_can_edit_body_and_price(tmp_path: Path) -> None:
    (tmp_path / "REVIEW_ON").touch()
    orchestrator = gate(tmp_path, 30)

    async def decide() -> None:
        draft = tmp_path / "review" / "7.json"
        while not draft.exists():
            await asyncio.sleep(0.05)
        assert json.loads(draft.read_text())["total"] == "100.00"
        decision = {
            "action": "send",
            "body": "New body 90.00 EUR.",
            "total": "90.00",
            "currency": "EUR",
        }
        (tmp_path / "review" / "7.decision.json").write_text(json.dumps(decision))

    reviewed, _ = await asyncio.gather(orchestrator.await_review(quote()), decide())
    assert reviewed is not None
    assert reviewed.body == "New body 90.00 EUR."
    assert reviewed.total == Decimal("90.00")


async def test_reviewer_hold_returns_none(tmp_path: Path) -> None:
    (tmp_path / "REVIEW_ON").touch()
    (tmp_path / "review").mkdir()
    (tmp_path / "review" / "7.decision.json").write_text(json.dumps({"action": "hold"}))
    assert await gate(tmp_path, 30).await_review(quote()) is None


async def test_no_decision_sends_draft_at_deadline(tmp_path: Path) -> None:
    (tmp_path / "REVIEW_ON").touch()
    orchestrator = gate(tmp_path, 0.5)
    assert await orchestrator.await_review(quote()) == quote()
    assert timedelta(seconds=0) < timedelta(seconds=1)


async def test_reviewer_text_without_a_price_is_never_sent(tmp_path: Path) -> None:
    """Round 121 (declined_in_scope): 'rate system unavailable, I will come back to you'."""
    (tmp_path / "REVIEW_ON").touch()
    (tmp_path / "review").mkdir()
    holding = ("Thank you for your request. The airline currently cannot confirm a rate, as its rate system "
               "is temporarily unavailable. I will come back to you with a confirmed all-in price as soon as "
               "the rate is available again.")
    (tmp_path / "review" / "7.decision.json").write_text(json.dumps({"action": "send", "body": holding}))
    reviewed = await gate(tmp_path, 30).await_review(quote())
    assert reviewed is not None and reviewed.body == "Our all-in price is 100.00 EUR."
