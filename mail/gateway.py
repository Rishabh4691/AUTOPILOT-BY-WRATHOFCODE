import os
import time
from dataclasses import dataclass

import httpx

from .config import settings

PRICES = {
    "gpt-5-nano": (0.05, 0.40),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-6-luna": (0.10, 0.50),
}


def price_per_m(model: str) -> tuple[float, float]:
    if os.getenv("LLM_PRICE_IN_PER_M") and os.getenv("LLM_PRICE_OUT_PER_M"):
        return float(os.environ["LLM_PRICE_IN_PER_M"]), float(os.environ["LLM_PRICE_OUT_PER_M"])
    key = next((k for k in sorted(PRICES, key=len, reverse=True) if model.lower().startswith(k)), None)
    return PRICES.get(key, (0.40, 1.60))


def reasoning_effort(model: str) -> str | None:
    forced = os.getenv("LLM_REASONING_EFFORT")
    if forced is not None:
        return forced or None
    m = model.lower()
    if m.startswith("gpt-5"):
        return "minimal"
    if m.startswith("gpt-6") or m.startswith("o"):
        return "none" if m.startswith("gpt-6") else "low"
    return None


@dataclass
class Reply:
    text: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    ms: int
    model: str


class GatewayError(Exception):
    pass


async def chat(messages, max_tokens=500, http: httpx.AsyncClient | None = None, timeout=25) -> Reply:
    body = {"model": settings.llm_model, "messages": messages, "max_completion_tokens": max_tokens}
    effort = reasoning_effort(settings.llm_model)
    if effort:
        body["reasoning_effort"] = effort
    own = http is None
    http = http or httpx.AsyncClient(timeout=timeout)
    t0 = time.monotonic()
    try:
        r = await http.post(
            f"{settings.gateway_url}/chat/completions",
            json=body,
            headers={"X-API-Key": settings.api_key, "Authorization": f"Bearer {settings.api_key}"},
        )
    except httpx.HTTPError as e:
        raise GatewayError(f"{type(e).__name__}: {e}") from e
    finally:
        if own:
            await http.aclose()
    if r.status_code >= 400:
        raise GatewayError(f"{r.status_code}: {r.text[:200]}")
    data = r.json()
    usage = data.get("usage") or {}
    p, c = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise GatewayError(f"bad response shape: {str(data)[:200]}") from e
    return Reply(
        text=text.strip(),
        prompt_tokens=p,
        completion_tokens=c,
        cost_usd=round(p * price_per_m(settings.llm_model)[0] / 1e6 + c * price_per_m(settings.llm_model)[1] / 1e6, 8),
        ms=int((time.monotonic() - t0) * 1000),
        model=data.get("model") or settings.llm_model,
    )
