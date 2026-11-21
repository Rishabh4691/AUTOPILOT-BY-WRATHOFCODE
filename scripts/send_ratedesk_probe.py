import json
import sys

import httpx

from core.config import auth_headers, load_settings
from scripts.probe import shape


def main() -> int:
    settings = load_settings()
    message = {
        "to": settings.rate_desk_address,
        "subject": "Rate request FRA-ORD",
        "body": "Hello,\n\nplease quote air freight FRA to ORD, 100 kg, 0.5 cbm, port to port.\n\n"
        "Thank you.",
    }
    with httpx.Client(
        base_url=settings.base_url, headers=auth_headers(settings), timeout=20
    ) as client:
        response = client.post("/v1/mailbox/messages", json=message)
    print("status", response.status_code)
    if response.is_success:
        stored = response.json()
        print("id", stored.get("id"))
        print("shape", json.dumps(shape(stored), indent=1))
    else:
        print(response.text[:500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
