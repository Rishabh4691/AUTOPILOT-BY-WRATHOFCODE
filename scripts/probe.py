import json
import sys
from typing import Any

import httpx

from core.config import auth_headers, load_settings


def shape(value: Any, depth: int = 0) -> Any:
    if isinstance(value, dict):
        return {key: shape(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [shape(value[0], depth + 1)] if value else []
    return type(value).__name__


def main() -> int:
    settings = load_settings()
    headers = auth_headers(settings)
    with httpx.Client(base_url=settings.base_url, headers=headers, timeout=20) as client:
        me = client.get("/v1/me")
        print("me status", me.status_code, "fields", sorted(me.json()) if me.is_success else "")
        poll = client.get("/v1/mailbox/messages", params={"since_id": 0, "limit": 200})
        print("poll status", poll.status_code)
        if poll.is_success:
            body = poll.json()
            print("poll shape", json.dumps(shape(body), indent=1))
            messages = body.get("messages") or body.get("items") or []
            print("message count", len(messages))
        models = client.get("/v1/gateway/models")
        print("models status", models.status_code)
        if models.is_success:
            for model in models.json().get("data", []):
                print("model", model.get("id"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
