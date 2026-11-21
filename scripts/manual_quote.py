import argparse
import asyncio
import dataclasses
import sys
import time
from datetime import UTC, datetime

import httpx

from core.agents.directory import load_directory
from core.agents.mailbox import HttpMailboxClient
from core.agents.trucker import parse_price
from core.config import Settings, auth_headers, load_settings
from core.contracts import RFQ, PickupPrice, PriceOption, Stage
from core.main import build, configure_logging
from core.store import Store


async def trucker_prices(client: httpx.AsyncClient, settings: Settings, rfq: RFQ) -> list[PickupPrice]:
    directory = load_directory(settings.kit_dir)
    since = max(0, rfq.mail_id - 1)
    body = (await client.get("/v1/mailbox/messages", params={"since_id": since, "limit": 200})).json()
    prices: list[PickupPrice] = []
    for message in body.get("messages", []):
        contact = directory.by_email(str(message.get("from", "")))
        if contact is None or contact.kind != "trucker":
            continue
        if f"Pickup request {rfq.mail_id}" not in str(message.get("subject", "")):
            continue
        parsed = parse_price(str(message.get("body", "")))
        if parsed is None:
            continue
        prices.append(
            PickupPrice(
                source="manual",
                trucker=contact.name,
                zone=rfq.pickup_zone or "",
                total=parsed[0],
                currency=parsed[1],
                received_at=datetime.now(UTC),
            )
        )
    return prices


async def gather_options(orchestrator_sources: list[object], rfq: RFQ) -> list[PriceOption]:
    options: list[PriceOption] = []
    for source in orchestrator_sources:
        try:
            found = await source.quote(rfq)  # type: ignore[attr-defined]
        except Exception as error:
            print(f"source {getattr(source, 'name', source)} failed: {type(error).__name__}: {error}")
            continue
        print(f"source {getattr(source, 'name', source)}: {len(found)} options")
        options.extend(found)
    return options


async def run(mail_id: int, send: bool, wait_pickup_s: float) -> int:
    base = load_settings()
    live_db = base.db_path
    settings = dataclasses.replace(
        base, dry_run=not send, db_path=live_db if send else live_db.with_name("preview.db")
    )
    store = Store(settings.db_path)
    try:
        async with httpx.AsyncClient(
            base_url=settings.base_url, headers=auth_headers(settings), timeout=15
        ) as client:
            orchestrator = build(settings, client, store)
            if send and store.outbox_status(mail_id, Stage.QUOTED) is not None:
                print(f"thread {mail_id} already has a quote, not sending")
                return 1
            mail = await HttpMailboxClient(client, settings).read_one(mail_id)
            rfq, _ = await orchestrator.extractor.extract(mail)
            print(
                f"rfq {rfq.origin}->{rfq.destination} {rfq.gross_kg} kg {rfq.volume_cbm} cbm "
                f"door={rfq.door_pickup} zone={rfq.pickup_zone} pref={rfq.preference.value} cur={rfq.currency}"
            )
            options = await gather_options(list(orchestrator.sources), rfq)
            for option in sorted(options, key=lambda o: (o.total, o.transit_days)):
                print(f"  {option.source} {option.carrier} {option.total} {option.currency} {option.transit_days}d")
            if not options:
                print("no options, cannot quote")
                return 1
            pickup = None
            if rfq.door_pickup:
                prices = await trucker_prices(client, settings, rfq)
                if not prices and orchestrator.pickup is not None:
                    await orchestrator.pickup.request(rfq)
                    deadline = time.monotonic() + wait_pickup_s
                    while not prices and time.monotonic() < deadline:
                        await asyncio.sleep(3)
                        prices = await trucker_prices(client, settings, rfq)
                for price in prices:
                    print(f"  pickup {price.trucker} {price.total} {price.currency}")
                eur = [p for p in prices if p.currency == "EUR"] or prices
                pickup = min(eur, key=lambda p: p.total) if eur else None
                if pickup is None:
                    print("door pickup but no trucker price yet")
                    return 1
            quote = await orchestrator.build_quote(rfq, options, pickup)
            if quote is None:
                print("quote held, see events")
                return 1
            print(f"QUOTE {quote.total} {quote.currency} via {quote.option.carrier} to {quote.to}")
            print(quote.body)
            if not send:
                print("preview only, pass --send to send")
                return 0
            from core.agents.booking import record_sent_quote

            if store._conn.execute("SELECT 1 FROM rfqs WHERE id=?", (str(mail_id),)).fetchone() is None:
                store.upsert_rfq(str(mail_id), str(mail.thread_root_id), mail.sender, mail.subject, mail.received_at, "new")
            await orchestrator.send_quote(quote)
            if store.outbox_status(quote.thread_root_id, Stage.QUOTED) == "sent":
                record_sent_quote(
                    store, mail_id, mail.thread_root_id, mail.sender, quote.subject, quote.option.carrier,
                    quote.total, quote.currency, quote.option.rate_id, quote.body, mail.received_at,
                )
            print(f"outbox status: {store.outbox_status(quote.thread_root_id, Stage.QUOTED)}")
    finally:
        store.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mail_id", type=int)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--wait-pickup", type=float, default=60.0)
    args = parser.parse_args()
    configure_logging()
    return asyncio.run(run(args.mail_id, args.send, args.wait_pickup))


if __name__ == "__main__":
    sys.exit(main())
