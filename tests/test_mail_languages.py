import asyncio

import pytest

from mail import gateway, writer


class Reply:
    def __init__(self, text: str) -> None:
        self.text, self.prompt_tokens, self.completion_tokens, self.model, self.cost_usd = text, 1, 1, "x", 0.0


@pytest.fixture
def model(monkeypatch):
    seen: dict = {}

    async def chat(messages, http=None):
        seen["prompt"] = messages[0]["content"]
        return Reply(seen["reply"])

    monkeypatch.setattr(gateway, "chat", chat)
    return seen


PRICE = {"carrier": "Solace Air Cargo", "total": 3680, "currency": "EUR", "transit_days": 1,
         "ready_date": "2026-11-26", "valid_until": "2026-11-26T18:00:00Z", "includes": ["freight", "fuel", "security"]}


def rfq(language: str, **extra) -> dict:
    base = {"language": language, "reference": "WOC-37587", "origin": "STR", "destination": "MIA", "pieces": 1,
            "gross_kg": 1986, "chargeable_kg": 2000, "goods": "hassas cihazlar", "first_name": "Sara",
            "door_pickup": False, "pickup_town": "", "preference": "cheapest",
            "customer_text": "Merhaba, en ucuz seçeneği istiyoruz. Sara", "subject": "STR-MIA hava navlun teklifi"}
    return {**base, **extra}


TURKISH = """Merhaba [FIRST],

Ayrıntılar için teşekkürler. [ORIGIN_CITY] çıkışlı [CARGO] için [CARRIER] ile gitmenizi öneririm, en uygun seçenek bu. Yük yaklaşık [ARRIVAL] tarihinde [DEST_CITY] varışlı olacak.

Hava navlunu, yakıt ve güvenlik dahil toplam fiyat [TOTAL].

Bu fiyatı [VALID] tarihine kadar tutabilirim, rezervasyon için kısa bir evet yeterli. Referansımız [REF].

Saygılarımla,
Lena Hartmann
WRATHOFCODE Air Freight"""


def test_round_126_turkish_prompt_carries_no_english_sentences(model) -> None:
    model["reply"] = TURKISH
    asyncio.run(writer.write_quote_email(rfq("tr"), PRICE))
    prompt = model["prompt"]
    assert 'First line is exactly "Merhaba [FIRST],"' in prompt
    assert "Saygılarımla," in prompt
    assert "[WARM]" not in prompt and "[PREF]" not in prompt and "[INCLUDED]" not in prompt
    assert "cheapest (that word in Turkish)" in prompt


def test_round_126_turkish_email_has_native_greeting_dates_and_price(model) -> None:
    model["reply"] = TURKISH
    email = asyncio.run(writer.write_quote_email(rfq("tr"), PRICE))
    assert email.fallback_reason is None
    body = email.body
    assert body.startswith("Merhaba Sara,")
    assert "3.680,00 EUR" in body and body.count("3.680,00") == 1
    assert "28.11.2026" in body
    for english in ("Thanks for the details", "cheapest", "for you today", "air freight, fuel and security", "Cheers"):
        assert english not in body


def test_chinese_greeting_is_not_doubled(model) -> None:
    model["reply"] = ("您好 [FIRST]，\n\n感谢询价。[CARGO]建议选择[CARRIER]，预计[ARRIVAL]到达。\n\n全包价格为[TOTAL]。\n\n"
                      "价格保留至[VALID]，参考号[REF]。\n\n此致\nLena Hartmann\nWRATHOFCODE Air Freight")
    email = asyncio.run(writer.write_quote_email(rfq("zh", goods="精密仪器", customer_text="您好，请报价。"), PRICE))
    assert email.body.count("您好") == 1


def test_pickup_town_is_a_placeholder_so_the_model_writes_no_postcode(model) -> None:
    model["reply"] = TURKISH
    asyncio.run(writer.write_quote_email(rfq("de", door_pickup=True, pickup_town="70275 Stuttgart",
                                             customer_text="Hallo, bitte Angebot. Sara"), PRICE))
    assert "their site in [PICKUP_TOWN]" in model["prompt"]
    assert "70275" not in model["prompt"].split("---")[0]


def test_german_fallback_route_has_no_english_word() -> None:
    _, values = writer.facts(rfq("de"), PRICE)
    assert " to " not in values["ROUTE"]


@pytest.mark.parametrize("phrase", ["la plus rapide", "la moins chère"])
def test_french_superlative_is_not_an_alternative(phrase: str) -> None:
    assert writer.alternatives(f"C'est {phrase} sur cette ligne.", "fr") == []
    assert writer.alternatives("Une option plus rapide existe.", "fr")
