import os
import time
from dataclasses import dataclass

import httpx

from .config import settings

PRICE_IN = float(os.getenv("LLM_PRICE_IN_PER_M") or 0.10)
PRICE_OUT = float(os.getenv("LLM_PRICE_OUT_PER_M") or 0.50)


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


async def chat(messages, max_tokens=700, http: httpx.AsyncClient | None = None, timeout=25) -> Reply:
    body = {"model": settings.llm_model, "messages": messages, "max_completion_tokens": max_tokens}
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
        cost_usd=round(p * PRICE_IN / 1e6 + c * PRICE_OUT / 1e6, 8),
        ms=int((time.monotonic() - t0) * 1000),
        model=data.get("model") or settings.llm_model,
    )
