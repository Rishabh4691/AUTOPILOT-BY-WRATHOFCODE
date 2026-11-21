from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import openai
import pytest

from core.config import Settings
from core.llm import GatewayLlmClient, LlmUnavailable, TokenBudget, price_for

SETTINGS = Settings(
    api_key="test-key",
    base_url="https://example.test",
    gateway_url="https://example.test/v1/gateway",
    kit_url="https://example.test/kit.zip",
    our_address="us@example.test",
    rate_desk_address="desk@example.test",
    tracking_address="track@example.test",
    dry_run=True,
    kill_switch=False,
    llm_model="gpt-5-nano",
    poll_interval_s=2.0,
    max_tokens_per_rfq=3000,
    db_path=Path("unused.db"),
    kit_dir=Path("unused"),
)


def bad_request() -> openai.BadRequestError:
    request = httpx.Request("POST", "https://example.test/v1/gateway/chat/completions")
    response = httpx.Response(400, request=request)
    return openai.BadRequestError("unsupported parameter", response=cast(Any, response), body=None)


def reply(text: str, prompt: int = 100, completion: int = 20, cost: Any = None) -> Any:
    usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, cost=cost)
    message = SimpleNamespace(content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


class FakeCompletions:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make(
    outcomes: list[Any], settings: Settings = SETTINGS
) -> tuple[GatewayLlmClient, FakeCompletions]:
    completions = FakeCompletions(outcomes)
    fake = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return GatewayLlmClient(settings, cast(openai.AsyncOpenAI, fake)), completions


async def test_primary_call_records_usage_and_cost() -> None:
    client, calls = make([reply("hello", 1000, 100)])
    result = await client.complete("sys", "user", 50, json_mode=True)
    assert result.text == "hello"
    assert result.usage.model == "gpt-5-nano"
    assert result.usage.input_tokens == 1000 and result.usage.output_tokens == 100
    assert result.usage.cost_usd == price_for("gpt-5-nano", 1000, 100)
    sent = calls.calls[0]
    assert sent["reasoning_effort"] == "minimal"
    assert sent["max_completion_tokens"] == 50
    assert sent["response_format"] == {"type": "json_object"}


async def test_reported_cost_wins() -> None:
    client, _ = make([reply("hi", cost=0.0123)])
    result = await client.complete("s", "u", 10)
    assert result.usage.cost_usd == Decimal("0.0123")


async def test_falls_back_once_on_rejection() -> None:
    client, calls = make([bad_request(), reply("fallback")])
    result = await client.complete("s", "u", 10)
    assert result.usage.model == "gpt-4.1-mini"
    assert "reasoning_effort" not in calls.calls[1]
    assert calls.calls[1]["model"] == "gpt-4.1-mini"


async def test_both_models_rejected() -> None:
    client, calls = make([bad_request(), bad_request()])
    with pytest.raises(LlmUnavailable):
        await client.complete("s", "u", 10)
    assert len(calls.calls) == 2


async def test_timeout_is_unavailable() -> None:
    request = httpx.Request("POST", "https://example.test")
    client, _ = make([openai.APITimeoutError(cast(Any, request))])
    with pytest.raises(LlmUnavailable):
        await client.complete("s", "u", 10)


async def test_empty_content_is_unavailable() -> None:
    client, _ = make([reply("   ")])
    with pytest.raises(LlmUnavailable):
        await client.complete("s", "u", 10)


async def test_kill_switch_never_calls() -> None:
    client, calls = make([reply("x")], replace(SETTINGS, kill_switch=True))
    with pytest.raises(LlmUnavailable):
        await client.complete("s", "u", 10)
    assert calls.calls == []


async def test_budget_refuses_and_records() -> None:
    budget = TokenBudget(200)
    client, calls = make([reply("ok", 60, 40)])
    await client.complete("s", "u", 100, budget=budget)
    assert budget.spent == 100
    with pytest.raises(LlmUnavailable):
        await client.complete("s", "u", 150, budget=budget)
    assert len(calls.calls) == 1
    assert budget.can_spend(100) and not budget.can_spend(101)


def test_unknown_model_has_no_price() -> None:
    assert price_for("mystery", 10, 10) is None
