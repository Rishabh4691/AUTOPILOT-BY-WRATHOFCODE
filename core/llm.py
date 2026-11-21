from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

import openai

from core.config import Settings
from core.contracts import LlmResult, LlmUsage

log = logging.getLogger("core.llm")

DEFAULT_MODEL = "gpt-5-nano"
FALLBACK_MODEL = "gpt-4.1-mini"
MILLION = Decimal(1_000_000)
PRICES_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-5-nano": (Decimal("0.05"), Decimal("0.40")),
    "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
}
REJECTED = (openai.BadRequestError, openai.NotFoundError, openai.UnprocessableEntityError)


class LlmUnavailable(Exception):
    pass


class TokenBudget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.spent = 0

    @property
    def left(self) -> int:
        return max(0, self.limit - self.spent)

    def can_spend(self, n: int) -> bool:
        return n <= self.left

    def record(self, n: int) -> None:
        self.spent += max(0, n)


def estimate_tokens(system: str, user: str, max_output_tokens: int) -> int:
    return len(system + user) // 3 + max_output_tokens


def price_for(model: str, input_tokens: int, output_tokens: int) -> Decimal | None:
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        prices = next((p for name, p in PRICES_PER_MTOK.items() if model.startswith(name)), None)
    if prices is None:
        return None
    return (prices[0] * input_tokens + prices[1] * output_tokens) / MILLION


def reported_cost(response: Any) -> Decimal | None:
    for holder in (getattr(response, "usage", None), response):
        value = getattr(holder, "cost", None) if holder is not None else None
        if value is None and holder is not None:
            extra = getattr(holder, "model_extra", None) or {}
            value = extra.get("cost")
        if isinstance(value, (int, float, str, Decimal)) and not isinstance(value, bool):
            try:
                return Decimal(str(value))
            except ArithmeticError:
                return None
    return None


def response_text(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    content = getattr(choices[0].message, "content", None)
    return content.strip() if isinstance(content, str) else ""


def token_counts(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return 0, 0
    return int(getattr(usage, "prompt_tokens", 0) or 0), int(
        getattr(usage, "completion_tokens", 0) or 0
    )


class GatewayLlmClient:
    def __init__(self, settings: Settings, client: openai.AsyncOpenAI | None = None) -> None:
        self.settings = settings
        self.model = settings.llm_model or DEFAULT_MODEL
        self.fallback_model = str(getattr(settings, "llm_fallback_model", "") or FALLBACK_MODEL)
        self.timeout_s = float(getattr(settings, "llm_timeout_s", 12) or 12)
        self.client = client or openai.AsyncOpenAI(
            base_url=settings.gateway_url,
            api_key=settings.api_key,
            timeout=self.timeout_s,
            max_retries=0,
        )

    async def complete(
        self,
        system: str,
        user: str,
        max_output_tokens: int,
        json_mode: bool = False,
        budget: TokenBudget | None = None,
    ) -> LlmResult:
        if self.settings.kill_switch:
            raise LlmUnavailable("kill switch is on")
        if budget is not None and not budget.can_spend(
            estimate_tokens(system, user, max_output_tokens)
        ):
            raise LlmUnavailable("token budget exhausted")
        result = await self._complete_with_fallback(system, user, max_output_tokens, json_mode)
        if budget is not None:
            budget.record(result.usage.input_tokens + result.usage.output_tokens)
        return result

    async def _complete_with_fallback(
        self, system: str, user: str, max_output_tokens: int, json_mode: bool
    ) -> LlmResult:
        try:
            return await self._call(self.model, system, user, max_output_tokens, json_mode, True)
        except REJECTED as error:
            log.warning(
                "llm_model_rejected", extra={"model": self.model, "error": type(error).__name__}
            )
        try:
            return await self._call(
                self.fallback_model, system, user, max_output_tokens, json_mode, False
            )
        except REJECTED as error:
            raise LlmUnavailable(f"both models rejected: {type(error).__name__}") from error

    async def _call(
        self,
        model: str,
        system: str,
        user: str,
        max_output_tokens: int,
        json_mode: bool,
        reasoning: bool,
    ) -> LlmResult:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": max_output_tokens,
            "timeout": self.timeout_s,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if reasoning:
            kwargs["reasoning_effort"] = "minimal"
        started = time.monotonic()
        try:
            response = await self.client.chat.completions.create(**kwargs)
        except (openai.APITimeoutError, openai.APIConnectionError) as error:
            raise LlmUnavailable(f"llm unreachable: {type(error).__name__}") from error
        except openai.APIStatusError as error:
            if isinstance(error, REJECTED):
                raise
            raise LlmUnavailable(f"llm error status {error.status_code}") from error
        return self._result(model, response, started)

    def _result(self, model: str, response: Any, started: float) -> LlmResult:
        duration_ms = int((time.monotonic() - started) * 1000)
        input_tokens, output_tokens = token_counts(response)
        cost = reported_cost(response)
        if cost is None:
            cost = price_for(model, input_tokens, output_tokens)
        log.info(
            "llm_call",
            extra={
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "duration_ms": duration_ms,
                "cost_usd": str(cost) if cost is not None else None,
            },
        )
        text = response_text(response)
        if not text:
            raise LlmUnavailable("llm returned empty content")
        usage = LlmUsage(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            duration_ms=duration_ms,
        )
        return LlmResult(text=text, usage=usage)
