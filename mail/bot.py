import asyncio
import logging
from typing import Awaitable, Callable

from . import poller, router, store
from .client import Mail

log = logging.getLogger("autopilot.bot")

Agent = Callable[[Mail, router.Route], Awaitable[None]]
AGENTS: dict[str, Agent] = {}
OWNER = {"rfq": "rfq", "followup": "rfq", "accept": "booking", "booking_confirm": "booking", "tracking": "tracking", "tariff": "tariff"}


def agent(*kinds):
    def wrap(fn):
        for k in kinds:
            AGENTS[k] = fn
        return fn

    return wrap


async def handle(mail: Mail):
    r = router.route(mail)
    fn = AGENTS.get(r.kind)
    if fn is None:
        if r.kind in OWNER:
            store.log_event(OWNER[r.kind], r.rfq_id, "todo", "info", f"No {r.kind} agent yet for mail {mail.id}")
        return
    await fn(mail, r)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(poller.main(handle))
    except poller.AlreadyRunning as e:
        raise SystemExit(str(e))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
