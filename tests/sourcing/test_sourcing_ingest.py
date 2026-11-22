from datetime import date
from decimal import Decimal as D

import sourcing.kit_parsers  # noqa: F401  (registers the rate-sheet parser)
from sourcing.ingest import ingest_tariff_mail, is_tariff_mail
from sourcing.kit import load_carriers
from sourcing.models import Shipment
from sourcing.sheets import get_sheet_prices
from sourcing.tariffs import TariffStore

DEC_SHEET = b"""Yellowtail Air Freight | Air export tariff
Currency    EUR
Valid from  01.12.2026
Valid to    31.12.2026
Chargeable weight is the higher of actual weight and volume weight (1 cbm = 167 kg).
Fuel and security surcharges are charged per kg of the weight the freight is billed on.
Lane        Transit     Minimum     -45       +45       +100      +250      +500      +1000     +2000
CGN-SYD              5  EUR 80.00   EUR 6.00  EUR 5.00  EUR 4.00  EUR 3.00  EUR 2.00  EUR 1.50  EUR 1.00
CGN-SYD: fuel EUR 1.00 per kg, security EUR 0.20 per kg
"""

MAIL = {
    "id": 501,
    "from": "Yellowtail Air Freight <yellowtail-air-freight@hackloop.mail>",
    "subject": "Tariff December 2026",
    "attachments": [{"id": 1, "filename": "yellowtail-2026-12.txt"}],
}


def test_new_month_replaces_old_from_its_start_date(tmp_path):
    from sourcing.kit import build

    store = TariffStore(tmp_path / "tariffs.json")
    for t in build(out=None)[0]:
        store.upsert(t, save=False)
    store.save()
    carriers = load_carriers()
    assert is_tariff_mail(MAIL, carriers)

    res = ingest_tariff_mail(MAIL, [("yellowtail-2026-12.txt", DEC_SHEET)], carriers, store)
    assert res.alarms == [] and res.stored == ["yellowtail-air-freight-2026-12"]
    assert any("supersedes yellowtail-air-freight-2026-11" in n for n in res.notes)

    s = Shipment(rfq_id="T", origin="CGN", destination="SYD", gross_weight=10)
    nov = [o for o in get_sheet_prices(s, store.active(date(2026, 11, 21))) if o.airline.startswith("Yellow")]
    dec = [o for o in get_sheet_prices(s, store.active(date(2026, 12, 2))) if o.airline.startswith("Yellow")]
    assert nov[0].tariff_id.endswith("2026-11") and nov[0].total == D("84.70")
    assert dec[0].tariff_id.endswith("2026-12") and dec[0].total == D("92.00")  # 80 + 10 x 1.20

    # reload from disk: the new version was saved
    assert len(TariffStore(tmp_path / "tariffs.json").all()) == 11


def test_unreadable_sheet_raises_alarm_and_changes_nothing(tmp_path):
    store = TariffStore(tmp_path / "tariffs.json")
    bad = DEC_SHEET.replace(b"EUR 3.00", b"EUR ??")
    res = ingest_tariff_mail(MAIL, [("yellowtail-2026-12.txt", bad)], load_carriers(), store)
    assert res.stored == [] and res.alarms
    assert store.all() == []


def test_mail_from_unknown_sender_is_not_a_tariff():
    assert not is_tariff_mail({**MAIL, "from": "someone@else.mail"}, load_carriers())
