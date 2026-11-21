from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Any

import httpx

log = logging.getLogger("core.http")

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_jitter = secrets.SystemRandom()
SENSITIVE_HEADERS = frozenset({"x-api-key", "authorization", "cookie", "set-cookie"})


class HttpGiveUp(Exception):
    def __init__(self, message: str, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def redact_headers(headers: httpx.Headers | dict[str, str]) -> dict[str, str]:
    return {
        key: ("<redacted>" if key.lower() in SENSITIVE_HEADERS else value)
        for key, value in dict(headers).items()
    }


def retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def backoff_seconds(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    ceiling = min(cap, base * (2**attempt))
    return _jitter.uniform(ceiling / 2, ceiling)


async def request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    deadline: float | None = None,
    call_timeout_s: float = 10.0,
    max_attempts: int = 4,
    retry_statuses: frozenset[int] = RETRYABLE_STATUS,
    **kwargs: Any,
) -> httpx.Response:
    attempt = 0
    while True:
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0.2:
            raise HttpGiveUp(f"{method} {url} gave up at the deadline")
        call_timeout = call_timeout_s if remaining is None else min(call_timeout_s, remaining)
        try:
            response = await client.request(method, url, timeout=call_timeout, **kwargs)
        except (httpx.TimeoutException, httpx.TransportError) as error:
            wait = backoff_seconds(attempt)
            log.warning("http_transport_error", extra={"url": url, "error": type(error).__name__})
        else:
            if response.status_code not in retry_statuses:
                return response
            wait = retry_after_seconds(response) or backoff_seconds(attempt)
            log.warning("http_retryable_status", extra={"url": url, "status": response.status_code})
            if attempt + 1 >= max_attempts:
                raise HttpGiveUp(
                    f"{method} {url} failed with {response.status_code}",
                    response.status_code,
                    response.text[:500],
                )
        attempt += 1
        if attempt >= max_attempts:
            raise HttpGiveUp(f"{method} {url} failed after {attempt} attempts")
        if deadline is not None and time.monotonic() + wait >= deadline:
            raise HttpGiveUp(f"{method} {url} would wait past the deadline")
        await asyncio.sleep(wait)
