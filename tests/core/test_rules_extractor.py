from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.agents.mailbox import parse_mail
from core.agents.rules_extractor import RulesFirstExtractor
from core.contracts import Preference
from mail import kit
from mail.config import settings as mail_settings
from tests.kit_root import KIT, needs_kit


@pytest.fixture(autouse=True)
def kit_settings(monkeypatch):
    monkeypatch.setattr(kit, "settings", mail_settings.__class__(kit_dir=KIT))
    kit.carriers.cache_clear()
    kit.pickup_zones.cache_clear()
    yield
    kit.carriers.cache_clear()
    kit.pickup_zones.cache_clear()


class Fallback:
    def __init__(self) -> None:
        self.calls = 0

    async def extract(self, mail):
        self.calls += 1
        raise RuntimeError("fallback used")


def mail(body: str, subject: str = "Request", sender: str = "lukas.weber@maschinen.mail"):
    return parse_mail(
        {
            "id": 812,
            "from": sender,
            "to": "wrathofcode@hackloop.mail",
            "subject": subject,
            "body": body,
            "in_reply_to": None,
            "references": [],
            "received_at": datetime.now(UTC).isoformat(),
            "attachments": [],
        }
    )


@needs_kit
async def test_rules_handle_german_rfq_without_llm():
    fb = Fallback()
    rfq, usage = await RulesFirstExtractor(fb).extract(
        mail(
            "Hallo,\nbitte ein Angebot nach Chicago (ORD).\n2 Kolli à 60 x 40 x 50 cm, je 35 kg\n"
            "1 Palette 120 x 80 x 150 cm, 210 kg je\nAbholung in 80331 München. Bitte die schnellste.\n"
            "Viele Grüße\nLukas"
        )
    )
    assert fb.calls == 0 and usage is None
    assert (rfq.origin, rfq.destination) == ("MUC", "ORD")
    assert rfq.gross_kg == Decimal("280")
    assert sum(p.count for p in rfq.pieces) == 3
    assert rfq.door_pickup and rfq.pickup_zone == "80"
    assert rfq.preference is Preference.FASTEST and not rfq.preference_assumed


@needs_kit
async def test_inches_and_pounds_become_cm_and_kg():
    rfq, _ = await RulesFirstExtractor(Fallback()).extract(
        mail("Quote FRA to DXB, 4 cartons 24 x 20 x 18 in, total 220 lbs.")
    )
    assert rfq.pieces[0].length_cm == Decimal("60.96")
    assert rfq.gross_kg == pytest.approx(Decimal("99.79"), abs=Decimal("0.01"))
    assert rfq.preference_assumed


async def test_unreadable_mail_goes_to_fallback():
    fb = Fallback()
    with pytest.raises(RuntimeError, match="fallback used"):
        await RulesFirstExtractor(fb).extract(mail("Hi, can you help with something?"))
    assert fb.calls == 1


@needs_kit
async def test_html_table_with_weight_each():
    body = (
        "<html><body><p>Guten Tag,</p><p>bitte um Angebot MUC &rarr; SIN:</p><table><tr>"
        "<td>3 Stk</td><td>60 x 40 x 50 cm</td><td>12,5 kg je</td></tr></table>"
        "<p>Abholung in 80331 M&uuml;nchen, m&ouml;glichst g&uuml;nstig.</p></body></html>"
    )
    rfq, usage = await RulesFirstExtractor(Fallback()).extract(mail(body, "Anfrage Luftfracht"))
    assert usage is None
    assert (rfq.origin, rfq.destination) == ("MUC", "SIN")
    assert sum(p.count for p in rfq.pieces) == 3
    assert rfq.gross_kg == Decimal("37.5")
    assert rfq.door_pickup and rfq.pickup_zone == "80"


@needs_kit
async def test_volume_in_cbm_and_count_without_dims():
    from core.agents.human_writer import piece_count
    from core.agents.sheets import to_shipment
    from sourcing.weights import chargeable_weight_kg

    body = (
        "Could you quote an all-in price in EUR for the fastest air freight option to ORD? "
        "Please arrange trucking from our site in 51447 Bergisch Gladbach to the departure airport.\n\n"
        "The shipment is ready for pickup on 2026-11-25. "
        "It's 12 pieces of printed marketing material, 676 kg gross and 5.79 cbm.\n\nSara"
    )
    rfq, usage = await RulesFirstExtractor(Fallback()).extract(
        mail(body, "Fastest air freight to ORD")
    )
    assert usage is None
    assert rfq.destination == "ORD" and rfq.door_pickup and rfq.pickup_zone == "51"
    assert rfq.volume_cbm == Decimal("5.79")
    assert chargeable_weight_kg(to_shipment(rfq)) == Decimal("967.0")
    assert piece_count(rfq) == 12
    assert str(rfq.ready_date) == "2026-11-25"


@needs_kit
async def test_live_rfq_432_postcode_reaches_trucker_and_name_is_person():
    from core.agents.trucker import request_body
    from mail.extract import find_first_name

    body = (
        "Dear Sir or Madam,\n\nCould you please quote the fastest air freight option to JFK "
        "(New York, US)? The shipment will be ready for pickup at our site in 61018 (Bad Homburg), "
        "Germany, on 2026-11-25. Please arrange trucking from our site to the departure airport.\n\n"
        "The shipment consists of 6 pieces of precision instruments, with a gross weight of 1233 kg "
        "and a total volume of 10.78 cbm.\n\nKind regards\nAnna Sonnberg\n"
        "Head of Purchasing and Logistics\nSonnberg Kaffeeroesterei GmbH"
    )
    m = mail(body, "Air freight quote request to JFK", "sonnberg-roesterei@hackloop.mail")
    rfq, usage = await RulesFirstExtractor(Fallback()).extract(m)
    assert usage is None and rfq.destination == "JFK" and rfq.pickup_zone == "61"
    text = request_body(rfq, "61", "Bad Homburg", "FRA")
    assert "postcode 61018" in text and "10.78 cbm" in text and "Pieces: 6" in text
    assert find_first_name(m.sender, body) == "Anna"
    assert (
        find_first_name(
            "lindqvist-medtech@hackloop.mail", "Hi,\n\nquote\n\nSara\nLindqvist Medtech"
        )
        == "Sara"
    )
