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
