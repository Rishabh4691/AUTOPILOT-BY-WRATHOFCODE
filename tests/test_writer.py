import re

import httpx
import pytest

from mail import store, writer
from mail.config import settings
from mail.writer import MONEY, TEMPLATES, alternatives, check_final, facts, preference, template, write_quote_email

RFQ = {
    "id": "RFQ-1",
    "reference": "WOC-0042",
    "first_name": "Anna",
    "language": "en",
    "origin": "MUC",
    "destination": "JFK",
    "pieces": 3,
    "gross_kg": 450,
    "chargeable_kg": 480.5,
    "preference": "cheapest",
    "subject": "Air freight quote MUC-JFK",
    "customer_text": "Hi, 3 pallets to New York, cheapest please. Thanks, Anna",
}
PRICE = {
    "total": 1387.35,
    "currency": "EUR",
    "carrier": "Borealis Freight Airways",
    "transit_days": 2,
    "valid_until": "2026-11-21T16:15:00+00:00",
    "includes": ["freight", "fuel", "security"],
}

GOOD = """Hi [FIRST],

thanks for sending this over, it's under reference [REF].
For [ROUTE] with [PIECES], [GROSS] gross and [CHARGEABLE] chargeable, I'd go with [CARRIER].
That's [TRANSIT] in transit, landing around [ARRIVAL].
All-in you're looking at [TOTAL], which covers [INCLUDED].
The rate holds until [VALID], so just reply yes and we'll book it.
Speak soon.

Cheers,
Lena
WRATHOFCODE Air Freight"""


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "settings", settings.__class__(db_path=tmp_path / "app.db"))
    store._ready.clear()


def gw(text=None, status=200, calls=None):
    def handler(req):
        if calls is not None:
            calls.append(req)
        if status != 200:
            return httpx.Response(status, text="boom")
        return httpx.Response(200, json={
            "model": "gpt-6-luna",
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 600, "completion_tokens": 200},
        })

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def one_total(body, currency="EUR"):
    found = MONEY.findall(body)
    return len(found) == 1 and currency in found[0]


async def test_llm_email_has_exactly_one_total_and_real_numbers():
    calls = []
    e = await write_quote_email(RFQ, PRICE, http=gw(GOOD, calls=calls))
    assert len(calls) == 1
    assert e.used_llm and e.fallback_reason is None
    assert one_total(e.body)
    assert "EUR 1,387.35" in e.body and "WOC-0042" in e.body and "480.5 kg" in e.body
    assert e.body.startswith("Hi Anna,")
    assert "3 pieces" in e.body
    assert e.subject == "Re: Air freight quote MUC-JFK"
    assert e.cost_usd == pytest.approx(600 * 0.10 / 1e6 + 200 * 0.50 / 1e6)


@pytest.mark.parametrize("bad", [
    GOOD.replace("[TOTAL]", "EUR 999.00"),
    GOOD.replace("[TOTAL], which", "[TOTAL] or maybe [TOTAL], which"),
    GOOD.replace("[PIECES],", "3 pieces,"),
    GOOD.replace("Hi [FIRST],", "Dear Sir or Madam,"),
    GOOD + " 🚀",
    "- [TOTAL]\n- [REF]",
])
async def test_bad_llm_draft_falls_back_to_template(bad):
    calls = []
    e = await write_quote_email(RFQ, PRICE, http=gw(bad, calls=calls))
    assert len(calls) == 1
    assert e.used_llm and e.fallback_reason
    assert one_total(e.body) and "EUR 1,387.35" in e.body
    assert "999" not in e.body


async def test_gateway_down_still_gives_clean_email():
    e = await write_quote_email(RFQ, PRICE, http=gw(status=503))
    assert not e.used_llm and e.cost_usd == 0
    assert one_total(e.body)
    with store.connect() as db:
        assert db.execute("SELECT status FROM events WHERE step='write'").fetchone()[0] == "fail"


@pytest.mark.parametrize("lang,total", [
    ("en", "EUR 1,387.35"), ("de", "1.387,35 EUR"), ("fr", "1 387,35 EUR"),
    ("es", "1.387,35 EUR"), ("it", "1.387,35 EUR"), ("pl", "1.387,35 EUR"),
])
def test_every_template_has_one_total(lang, total):
    _, values = facts({**RFQ, "language": lang}, PRICE)
    body = template(lang, values)
    assert not check_final(body, values)
    assert body.count(total) == 1
    assert not re.search(r"\[[A-Z]+\]", body)
    assert 8 <= len([l for l in body.splitlines() if l.strip()]) <= 14


def test_template_without_first_name():
    _, values = facts({**RFQ, "first_name": "", "language": "fr"}, PRICE)
    assert template("fr", values).startswith("Bonjour,")


def test_unknown_language_uses_english():
    lang, values = facts({**RFQ, "language": "xx"}, PRICE)
    assert lang == "en" and template(lang, values).startswith("Hi Anna,")


def test_usd_total():
    _, values = facts(RFQ, {**PRICE, "currency": "USD", "total": 2050})
    body = template("en", values)
    assert "USD 2,050.00" in body and one_total(body, "USD")


FORBIDDEN = re.compile(r"alternativ|\boptions?\b|\bor we can\b|\bor\b|opci[oó]n|opzion|opcj|insurance", re.I)


def assert_one_decision(body, lang="en"):
    assert len(MONEY.findall(body)) == 1, f"more than one price: {MONEY.findall(body)}"
    assert not FORBIDDEN.search(body), f"offers an alternative: {FORBIDDEN.search(body).group(0)!r}"
    assert not alternatives(body.replace(PRICE["carrier"], ""), lang)


@pytest.mark.parametrize("lang", ["en", "de", "fr", "es", "it", "pl"])
def test_templates_give_one_reply_one_decision(lang):
    _, values = facts({**RFQ, "language": lang}, PRICE)
    assert_one_decision(template(lang, values), lang)


async def test_llm_email_gives_one_reply_one_decision():
    e = await write_quote_email(RFQ, PRICE, http=gw(GOOD))
    assert e.fallback_reason is None
    assert_one_decision(e.body)


@pytest.mark.parametrize("extra", [
    "Alternatively, we could ship via DXB.",
    "If you prefer, there is another option via FRA.",
    "Or we can look at a faster routing.",
    "We can also add insurance if you like.",
    "Happy to check a cheaper carrier as well.",
])
async def test_alternative_in_llm_draft_is_replaced(extra):
    draft = GOOD.replace("Speak soon.", extra)
    e = await write_quote_email(RFQ, PRICE, http=gw(draft))
    assert e.fallback_reason and "alternative" in e.fallback_reason
    assert_one_decision(e.body)


def test_second_price_is_caught():
    _, values = facts(RFQ, PRICE)
    body = template("en", values) + "\nExpress would be EUR 1,900.00."
    assert check_final(body, values)
    with pytest.raises(AssertionError):
        assert_one_decision(body)


@pytest.mark.parametrize("asked,want", [(None, "cheapest"), ("", "cheapest"), ("cheapest", "cheapest"), ("best price", "cheapest"), ("fastest", "fastest"), ("urgent", "fastest"), ("express", "fastest")])
def test_default_preference_is_cheapest(asked, want):
    assert preference(asked) == want
