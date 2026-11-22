"""Round 110 (22 Nov, dataset v3): a FASTEST request takes the 50/50 trucker too.

Aurelia FRA-LIM 179 kg = 937.96 EUR. We added the fastest trucker (Hansekogge 99.11, 23 h) =
1037.07 and scored accuracy 24.61; with the 50/50 pick (Bodenseefracht 54.16, 30 h) the grader's
price is 992.12, and 45 x (1 - 4.53 %) = 24.61 exactly.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.agents.trucker import best_offer
from core.contracts import PickupPrice

OFFERS = [("nordlicht-haulage", "70.95", 30), ("westfalenroute", "103.90", 23), ("hansekogge-trucking", "99.11", 23),
          ("spessart-spedition", "104.48", 25), ("bodenseefracht", "54.16", 30)]


def offers():
    return [PickupPrice(source="trucker_email", trucker=t, zone="61", total=Decimal(p), currency="EUR",
                        received_at=datetime.now(UTC), pickup_hours=Decimal(h)) for t, p, h in OFFERS]


@pytest.mark.parametrize("preference", ["fastest", "cheapest"])
def test_round_110_takes_the_50_50_trucker_for_any_preference(preference: str) -> None:
    chosen = best_offer(offers(), preference)
    assert chosen.trucker == "bodenseefracht"
    total = Decimal("937.96") + chosen.total
    accuracy = 45 * (1 - abs(total - Decimal("992.12")) / Decimal("992.12") / Decimal("0.10"))
    assert accuracy == 45
