"""Field extraction in the customer's language (suggested-changes section 15).

The same real shipments written in German, French, Dutch and Portuguese with local number and date
formats were read wrongly: 0 % DE/NL/PT, 55 % FR ("1 225 kg" with a narrow no-break space was 225 kg).
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from mail import kit
from mail.config import settings as mail_settings
from mail.extract import extract

KIT = Path(__file__).parent / "core" / "fixtures" / "kit"


@pytest.fixture(autouse=True)
def kit_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kit, "settings", mail_settings.__class__(kit_dir=KIT))


CASES = [
    ("de", "Guten Tag,\n\nbitte senden Sie uns Ihr schnellstes Angebot für Luftfracht nach EZE (Buenos Aires).\n"
           "Bitte holen Sie die Ware bei uns in 70498 Stuttgart, Deutschland, ab und organisieren Sie den LKW zum Abflughafen.\n"
           "Die Sendung ist am 28.11.2026 versandbereit: 11 Packstücke, Bruttogewicht 544 kg, Volumen 1,86 cbm.\n\n"
           "Mit freundlichen Grüßen\nAnna Müller",
     dict(origin="STR", door=True, zone="70", pieces=11, gross="544", cbm="1.86", pref="fastest", ready=date(2026, 11, 28))),
    ("fr", "Bonjour,\n\npourriez-vous nous coter votre offre de fret aérien la moins chère vers PVG (Shanghai) ?\n"
           "Enlèvement chez nous à 63198 Offenbach, Allemagne ; merci d'organiser le camion jusqu'à l'aéroport de départ.\n"
           "La marchandise sera prête le 25/11/2026 : 9 colis, poids brut 1 225 kg, volume 4,62 m3.\n\nCordialement\nClaire Martin",
     dict(origin="FRA", door=True, zone="63", pieces=9, gross="1225", cbm="4.62", pref="cheapest", ready=date(2026, 11, 25))),
    ("nl", "Goedendag,\n\nkunt u een offerte sturen voor de snelste luchtvracht naar PVG (Shanghai)?\n"
           "Wij leveren de goederen zelf af op luchthaven MUC.\n"
           "De zending is klaar op 28-11-2026: 9 colli, brutogewicht 134 kg, volume 0,77 m3.\n\nMet vriendelijke groet\nJan de Vries",
     dict(origin="MUC", door=False, zone=None, pieces=9, gross="134", cbm="0.77", pref="fastest", ready=date(2026, 11, 28))),
    ("pt", "Olá,\n\npoderiam cotar a opção de frete aéreo mais rápida para EZE (Buenos Aires)?\n"
           "Recolha nas nossas instalações em 70498 Stuttgart, Alemanha; por favor organizem o camião até ao aeroporto de partida.\n"
           "A carga estará pronta em 28/11/2026: 11 volumes, peso bruto 544 kg, volume 1,86 m3.\n\nCumprimentos\nAna Silva",
     dict(origin="STR", door=True, zone="70", pieces=11, gross="544", cbm="1.86", pref="fastest", ready=date(2026, 11, 28))),
]


@pytest.mark.parametrize(("lang", "body", "want"), CASES, ids=[c[0] for c in CASES])
def test_fields_are_read_in_the_customers_language(lang, body, want) -> None:
    x = extract("Air freight request", body, f"kunde-{lang}@example.mail", "1")
    s = x.shipment
    assert s is not None, x.missing
    assert (s.origin, s.door_pickup, s.pickup_zone) == (want["origin"], want["door"], want["zone"])
    assert x.pieces == want["pieces"]
    assert Decimal(str(x.gross_kg)) == Decimal(want["gross"])
    assert s.volume_cbm == Decimal(want["cbm"])
    assert x.preference == want["pref"]
    assert s.ready_date == want["ready"]


ROUND_149 = """안녕하세요,

2026-11-27에 독일 Fulda 36030에 있는 저희 사업장에서 픽업 가능합니다. 공항까지 트럭 운송도 함께 주선해 주세요.

화물은 기계 부품 12개이며, 총중량은 2802.08 lb, 부피는 150.45 cubic feet입니다.

KUL(Kuala Lumpur, MY)까지 가장 빠른 옵션으로, 픽업을 포함한 모든 비용을 EUR로 견적 부탁드립니다.

Mira Petersen
Nordlicht Audio"""


def test_round_149_korean_fastest_and_ready_date():
    from datetime import date

    from mail.extract import extract, find_ready

    r = extract("KUL행 항공 운송 견적 요청", ROUND_149, "nordlicht-audio@hackloop.mail", "44326")
    assert r.preference == "fastest" and r.preference_stated
    assert find_ready(ROUND_149) == date(2026, 11, 27)


@pytest.mark.parametrize("text, pref, ready", [
    ("픽업은 2026-11-24부터 가능하며 가장 저렴한 옵션으로 견적 부탁드립니다.", "cheapest", "2026-11-24"),
    ("请报价最便宜的方案，2026-11-28可提货。", "cheapest", "2026-11-28"),
    ("最快的选项，2026-11-26提货", "fastest", "2026-11-26"),
    ("一番安い方法でお願いします。2026-11-29に集荷可能です。", "cheapest", "2026-11-29"),
])
def test_cjk_preference_and_ready(text, pref, ready):
    from mail.extract import extract, find_ready

    r = extract("Quote", text, "x@hackloop.mail", "1")
    assert r.preference == pref and r.preference_stated
    assert str(find_ready(text)) == ready
