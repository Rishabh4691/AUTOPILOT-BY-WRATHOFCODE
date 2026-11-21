"""Round 42 (ULN, cheapest): rejected as excluded_airline.

Exclusions themselves are handled in mail/exclusions.py (56f3d51). This covers the two gaps left:
we still sent the excluded airline a bid request, and "pickup takes 25 hours" was not read, so a
25 h trucker passed the 24 h pickup rule.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from core.agents.airline_bids import excluded_airlines
from core.agents.trucker import best_offer, parse_hours
from core.contracts import RFQ, PickupPrice, Preference
from mail.exclusions import is_excluded

NOW = datetime(2026, 11, 21, 19, 10, tzinfo=UTC)


def rfq(notes: tuple[str, ...]) -> RFQ:
    return RFQ(mail_id=10831, thread_root_id=10831, customer="meyer-industrie@hackloop.mail",
               subject="Air freight quote request to ULN", origin="FRA", destination="ULN", pieces=(),
               gross_kg=Decimal("911"), volume_cbm=Decimal("3.27"), door_pickup=True, pickup_zone="65",
               preference=Preference.CHEAPEST, preference_assumed=False, received_at=NOW, notes=notes)


def test_excluded_airline_gets_no_bid_request() -> None:
    banned = excluded_airlines(rfq(("exclude_carrier: Zephyr Steppe Cargo",)))
    assert banned == ["Zephyr Steppe Cargo"]
    serving = ["Zephyr Steppe Cargo", "Himalaya Bridge Air", "Lagoon Isles Airways", "Pampero Air Cargo"]
    asked = [name for name in serving if not is_excluded(name, None, banned)]
    assert asked == ["Himalaya Bridge Air", "Lagoon Isles Airways", "Pampero Air Cargo"]
    assert excluded_airlines(rfq(())) == []


def test_round42_pickup_takes_25_hours_is_read_and_skipped(monkeypatch) -> None:
    monkeypatch.setenv("PICKUP_RULE", "fast_cheapest")  # the pre-brief rule this test covers
    assert parse_hours("Our all-in price is 165.10 EUR, and pickup takes 25 hours.") == Decimal("25")
    assert parse_hours("valid until 21 Nov 2026 19:25 UTC") is None
    offers = [("165.10", parse_hours("pickup takes 25 hours")), ("195.10", Decimal("17")),
              ("118.66", Decimal("31")), ("248.54", Decimal("8"))]
    prices = [PickupPrice(source="t", trucker=t, zone="65", total=Decimal(t), currency="EUR",
                          received_at=NOW, pickup_hours=h) for t, h in offers]
    assert best_offer(prices, "cheapest").total == Decimal("195.10")


def test_exclusion_from_an_earlier_mail_is_learned_at_start_and_applied_later(monkeypatch) -> None:
    import asyncio
    import json
    from pathlib import Path

    from core.agents.extractor import RegexRfqExtractor
    from core.agents.mailbox import parse_mail
    from core.agents.rules_extractor import RulesFirstExtractor
    from core.config import load_settings
    from mail import exclusions, kit
    from mail.config import settings as mail_settings

    fixtures = Path(__file__).parent / "fixtures"
    monkeypatch.setattr(kit, "settings", mail_settings.__class__(kit_dir=fixtures / "kit"))
    r42 = json.loads((fixtures / "mail" / "real_rfq_10831.json").read_text(encoding="utf-8"))
    # Round 42 arrived before the memory existed: nothing remembered yet.
    assert exclusions.recall(r42["from"]) == []
    assert exclusions.learn([r42, {"id": 1, "from": "zephyr-steppe-cargo@hackloop.mail",
                                    "body": "Please do not use Pampero Air Cargo."}]) == 1
    assert "Zephyr Steppe Cargo" in exclusions.recall(r42["from"])
    assert exclusions.recall("zephyr-steppe-cargo@hackloop.mail") == []  # carriers are not customers
    # The same customer's next request, with no mention of Zephyr, still excludes it.
    nxt = dict(r42, id=11999, body=r42["body"].split("Please do not offer")[0])
    settings = load_settings(environ={"FIVEU_API_KEY": "k"})
    later, _ = asyncio.run(RulesFirstExtractor(RegexRfqExtractor(settings, None)).extract(parse_mail(nxt)))
    assert "exclude_carrier: Zephyr Steppe Cargo" in later.notes
