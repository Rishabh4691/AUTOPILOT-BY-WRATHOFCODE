"""Customer questions in other languages (roadmap section 17).

Before, question detection was English-only, so a German or French customer's question about
departure, arrival, drop-off or a single air waybill was never answered.
"""

import pytest

from mail.writer import asked, question_slots

QUESTIONS = [
    ("Bitte bestätigen Sie den frühestmöglichen Abflug und die Ankunft.", {"departure", "arrival"}),
    ("Wann ist der späteste Anlieferschluss in MUC?", {"dropoff"}),
    ("Bitte alle Lose unter einem einzigen Luftfrachtbrief versenden.", {"awb"}),
    ("Merci de confirmer le départ au plus tôt et l'arrivée.", {"departure", "arrival"}),
    ("Quel est le délai de transit vers Delhi ?", {"arrival"}),
    ("¿Cuál es la hora límite de entrega en MUC?", {"dropoff"}),
    ("Qual è il tempo di transito per Bangkok?", {"arrival"}),
    ("Proszę potwierdzić najwcześniejszy wylot i przylot.", {"departure", "arrival"}),
    ("Wat is de transittijd naar Dallas?", {"arrival"}),
    ("Enviem todos os lotes sob um único conhecimento aéreo.", {"awb"}),
]


@pytest.mark.parametrize("text,want", QUESTIONS)
def test_question_is_recognised(text: str, want: set[str]) -> None:
    assert want <= asked(text)


@pytest.mark.parametrize("text", [
    "Wir bitten um ein Angebot für Luftfracht, die Ware ist bereit.",
    "Wir liefern die Ware selbst zum Abflughafen MUC.",
    "Entregamos la mercancía en el aeropuerto de salida.",
    "La marchandise sera prête le 25/11/2026 : 6 colis, poids brut 850 kg.",
])
def test_plain_request_has_no_question(text: str) -> None:
    assert asked(text) == set()


def test_german_question_reaches_the_prompt() -> None:
    hint = question_slots({"customer_text": "Wann ist die Ankunft in Chicago?"}, {}, "de")
    assert "[ARRIVAL]" in hint and "no extra question" not in hint
