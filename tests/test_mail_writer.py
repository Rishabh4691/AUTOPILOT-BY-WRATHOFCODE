import re

import httpx
import pytest

from mail import writer
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

Thanks for sending this over, it's under reference [REF].
For [ROUTE] with [PIECES], [GROSS] gross and [CHARGEABLE] chargeable, I'd go with [CARRIER].
That's [TRANSIT] in transit, landing around [ARRIVAL].
All-in you're looking at [TOTAL], which covers [INCLUDED].
The rate holds until [VALID], so just reply yes and we'll book it.
Speak soon.

Cheers,
Lena
WRATHOFCODE Air Freight"""


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
    assert e.cost_usd > 0


@pytest.mark.parametrize("bad", [
    GOOD.replace("[TOTAL]", "EUR 999.00"),
    GOOD.replace("[TOTAL], which", "[TOTAL] or maybe [TOTAL], which"),
    GOOD.replace("[PIECES],", "17 pieces,"),  # a number that is neither ours nor the customer's
    GOOD.replace("Speak soon.", "We are pleased to inform you of this offer."),
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
    assert one_total(e.body) and e.fallback_reason


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
    assert 7 <= len([l for l in body.splitlines() if l.strip()]) <= 14


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


async def test_duplicate_unit_and_blank_lines_are_cleaned():
    draft = GOOD.replace("with [PIECES],", "with [PIECES] pieces,").replace("Hi [FIRST],\n", "Hi [FIRST],\n  \n\n")
    e = await write_quote_email(RFQ, PRICE, http=gw(draft))
    assert "3 pieces pieces" not in e.body and "3 pieces," in e.body
    assert "\n\n\n" not in e.body and not any(l != l.rstrip() for l in e.body.splitlines())


async def test_dashes_and_curly_quotes_never_reach_the_customer():
    dashed = GOOD.replace("Thanks for sending this over,", "Thanks for sending this over —")
    e = await write_quote_email(RFQ, PRICE, http=gw(dashed))
    assert e.fallback_reason is None
    assert not re.search("[—–“”‘’„]", e.body)
    curly = GOOD.replace("we'll", "we’ll")
    e = await write_quote_email(RFQ, PRICE, http=gw(curly))
    assert e.fallback_reason is None and "we'll" in e.body
    assert not re.search("[—–“”‘’„]", e.body)


@pytest.mark.parametrize("filler", ["Thanks for reaching out!", "Let me know if you have any questions.", "Feel free to call me."])
async def test_chatbot_filler_falls_back(filler):
    e = await write_quote_email(RFQ, PRICE, http=gw(GOOD.replace("Speak soon.", filler)))
    assert e.fallback_reason and "stiff" in e.fallback_reason


@pytest.mark.parametrize("lang", ["en", "de", "fr", "es", "it", "pl"])
def test_templates_have_no_dashes_or_curly_quotes(lang):
    _, values = facts({**RFQ, "language": lang}, PRICE)
    assert not re.search("[—–“”‘’„]", template(lang, values))


async def test_greeting_line_is_always_set_by_code():
    e = await write_quote_email(RFQ, PRICE, http=gw(GOOD.replace("Hi [FIRST],", "Dear ANNA,")))
    assert e.body.startswith("Hi Anna,")


async def test_customer_dates_and_postcodes_are_allowed_in_llm_text():
    from mail.writer import facts, problems

    rfq = dict(RFQ, customer_text="Pickup in 61391 Bad Homburg, ready on 2026-11-28.")
    _, values = facts(rfq, PRICE)
    draft = GOOD.replace("Speak soon.", "We'll collect in 61391 once it's ready on 2026-11-28. Speak soon.")
    assert "model wrote digits" not in problems(draft, values, rfq["customer_text"])
    assert "model wrote digits" in problems(draft.replace("61391", "99999"), values, rfq["customer_text"])


def test_every_sentence_and_paragraph_starts_with_a_capital():
    from mail.writer import facts, template

    _, values = facts(RFQ, PRICE)
    body = template("en", values)
    for paragraph in [p for p in body.split("\n\n") if p.strip()][1:]:
        first = next(c for c in paragraph if c.isalpha())
        assert first.isupper(), paragraph
    assert not re.search(r"[.!?]\s+[a-z]", body.replace("e.g.", ""))
    assert " 0" not in body.split("arriv")[-1][:30]


def test_known_names_are_cased_exactly():
    from mail.writer import facts, fill

    _, values = facts(dict(RFQ, origin="fra", destination="del"), dict(PRICE, carrier="Borealis Freight Airways"))
    text = fill("Hi [FIRST],\n\nwe fly from frankfurt to DELHI with borealis freight airways. Total [TOTAL]. Ref [REF].", values)
    assert "Frankfurt" in text and "Delhi" in text and "Borealis Freight Airways" in text
    assert "\n\nWe fly" in text


def test_direct_questions_are_found_by_rules():
    from mail.writer import asked

    assert asked("Could you confirm the earliest available departure and arrival?") == {"departure", "arrival"}
    assert asked("Please send both lots together as one consignment under a single air waybill.") == {"awb"}
    assert asked("Could you also let me know the latest drop-off time at STR?") == {"dropoff"}
    assert asked("When can your truck collect it?") == {"pickup"}
    assert asked("Hi, 3 pallets to New York, cheapest please. Ready for pickup on 2026-11-28.") == set()


def test_answers_use_computed_dates_and_only_what_was_asked(monkeypatch):
    from datetime import date as real_date

    class FixedDate(real_date):
        @classmethod
        def today(cls):
            return real_date(2026, 11, 21)

    monkeypatch.setattr(writer, "date", FixedDate)
    text = ("Please send both lots as one consignment under a single air waybill and confirm "
            "the earliest available departure and arrival.")
    rfq = {**RFQ, "customer_text": text}
    _, values = facts(rfq, {**PRICE, "ready_date": "2026-11-28", "transit_days": 2})
    # ready Sat 28 Nov, flies Sun 29 Nov, 2 days transit, lands Tue 1 Dec: the dates add up
    assert values["DEPARTURE"] == "Sun 29 Nov"
    assert values["DEPARTURE_LINE"] == "The earliest departure is Sun 29 Nov."
    assert values["AWB_LINE"] == "All lots travel together as one consignment under a single air waybill."
    assert values["ARRIVAL_LINE"] == "Transit is 2 days."
    assert values["DROPOFF_LINE"] == "" and values["PICKUP_DATE_LINE"] == ""
    body = template("en", values)
    assert "around Tue 1 Dec" in body and "ready on Sat 28 Nov" in body
    assert "single air waybill" in body and "earliest departure is Sun 29 Nov" in body
    assert not re.search(r"\d{4}-\d{2}-\d{2}", body)
    plain = template("en", facts(RFQ, {**PRICE, "ready_date": "2026-11-28"})[1])
    assert "air waybill" not in plain and "earliest departure" not in plain


def test_arrival_is_never_before_ready_date_and_past_ready_uses_today():
    from datetime import date

    from mail.writer import arrival_date, departure_date, quote_arrival

    today = date(2026, 11, 21)
    assert departure_date("2026-11-19", today) == today
    assert arrival_date("2026-11-19", 2, today) == date(2026, 11, 24)
    assert arrival_date("2026-11-28", 2, today) == date(2026, 12, 1)
    assert arrival_date(None, None, today) == date(2026, 11, 22)
    stale = {"arrival": "2026-11-20", "ready_date": "2026-11-28", "transit_days": 2}
    assert quote_arrival(stale, today) == date(2026, 12, 1)


def test_one_price_format_everywhere():
    from mail.writer import money

    assert money(1234.56, "EUR") == "EUR 1,234.56"
    assert money(324.36, "eur") == "EUR 324.36"
    assert money(1234567.8, "USD", "en") == "USD 1,234,567.80"


@pytest.mark.parametrize("bad", [
    "We fly MUC → JFK.",
    "The rate holds until 16:15 UTC.",
    "That is 3 piece(s).",
    "Here is one all-in price.",
    "This is the best fit for you.",
    "The cheapest routing is the routing we like.",
    "It is “great”.",
    "Ready on 2026-11-28.",
    "It is booked.",
])
def test_robotic_drafts_fall_back(bad):
    from mail.writer import problems

    _, values = facts(RFQ, PRICE)
    assert problems(GOOD.replace("Speak soon.", bad), values, RFQ["customer_text"])


def test_lowercase_first_word_after_greeting_falls_back():
    from mail.writer import problems

    _, values = facts(RFQ, PRICE)
    draft = GOOD.replace("Thanks for sending", "thanks for sending")
    assert "lowercase first word after greeting" in problems(draft, values)
    assert not problems(GOOD, values)


async def test_draft_must_carry_the_needed_answers_and_uses_one_call():
    rfq = {**RFQ, "customer_text": "Please ship it under a single air waybill."}
    calls = []
    e = await write_quote_email(rfq, PRICE, http=gw(GOOD, calls=calls))
    assert len(calls) == 1
    assert e.fallback_reason and "unanswered" in e.fallback_reason
    assert "single air waybill" in e.body
    prompt = calls[0].content.decode()
    assert "[AWB_LINE]" in prompt and "[DEPARTURE_LINE]" not in prompt
    ok = await write_quote_email(rfq, PRICE, http=gw(GOOD.replace("Speak soon.", "[AWB_LINE]")))
    assert ok.fallback_reason is None and "single air waybill" in ok.body


def test_closing_line_varies_by_reference_but_is_stable():
    from mail.writer import CLOSINGS, closing_line

    assert {closing_line(f"WOC-{n}") for n in range(20)} == set(CLOSINGS)
    assert closing_line("WOC-1234") == closing_line("WOC-1234")
    for ref in ("WOC-1", "WOC-2", "WOC-3", "WOC-4"):
        values = facts({**RFQ, "reference": ref}, PRICE)[1]
        body = template("en", values)
        assert closing_line(ref) in body and f"Our reference is {ref}." in body
        assert not check_final(body, values)


def test_friendly_customer_gets_a_matching_signoff():
    rfq = {**RFQ, "customer_text": "Thanks a lot and have a lovely day!\nPetra"}
    assert "Have a lovely day too,\n" in template("en", facts(rfq, PRICE)[1])


async def test_empty_optional_sentence_never_breaks_a_line():
    draft = GOOD.replace("Speak soon.", "[VOLUME_NOTE]")
    e = await write_quote_email({**RFQ, "chargeable_kg": 450}, PRICE, http=gw(draft))
    assert "  " not in e.body and "[VOLUME_NOTE]" not in e.body


async def test_one_gateway_blip_is_retried_so_the_quote_keeps_its_cost_points():
    # A quote sent without a model call scores 0 cost points (rounds 7, 11, 28).
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(200, json={
            "model": "gpt-4.1-mini",
            "choices": [{"message": {"content": GOOD}}],
            "usage": {"prompt_tokens": 600, "completion_tokens": 200},
        })

    e = await write_quote_email(RFQ, PRICE, http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert len(calls) == 2 and e.used_llm


async def test_gateway_down_twice_falls_back_after_two_tries():
    calls = []
    e = await write_quote_email(RFQ, PRICE, http=gw(status=503, calls=calls))
    assert len(calls) == 2 and not e.used_llm and one_total(e.body)


def test_writer_model_default_is_gpt_4_1():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert 'or "gpt-4.1"' in (root / "mail" / "config.py").read_text(encoding="utf-8")
    assert "WRITER_MODEL=gpt-4.1-mini" in (root / ".env.example").read_text(encoding="utf-8")


def test_check_final_rejects_round_38_glitches() -> None:
    from mail.writer import check_final

    values = {"TOTAL": "EUR 1,921.60", "CARRIER": "Meridian Freightways"}
    good = (
        "Hi Anna,\n\nMeridian Freightways is the fastest way. The all-in price is EUR 1,921.60.\n"
        "I can hold it for about 14 minutes. Our reference is WOC-9877.\n\n"
        "Kind regards,\nLena Hartmann\nExport Air Freight, WRATHOFCODE Air Freight"
    )
    assert check_final(good, values) == []
    bad = (
        "Hi Anna,\n\nWOC-9877 Meridian Freightways is the fastest way. The all-in price is EUR 1,921.60. "
        "You can hold this booking until for about 14 minutes. Our reference is WOC-9877.\n\nKind regards,"
    )
    issues = check_final(bad, values)
    assert "reference misplaced or repeated" in issues
    assert "doubled preposition" in issues
    assert "missing signature" in issues


def test_harmless_words_no_longer_force_the_template() -> None:
    from mail.writer import check_final, problems

    values = {"TOTAL": "EUR 2,782.10", "CARRIER": "Ibisair Cargo", "REF": "WOC-1", "FIRST": "Klaus"}
    draft = (
        "Hi [FIRST],\n\n[WARM] For your goods I would go with [CARRIER]. Transit is five days, "
        "give or take a day, and we can collect within 24 hours.\n\nYour all-in price is [TOTAL]. "
        "Reply yes and I'll get it booked. Our reference is [REF].\n\nCheers,\nLena Hartmann\n"
        "WRATHOFCODE Air Freight"
    )
    values["WARM"] = "Thanks for the details."
    customer = "Please collect within 24 hours if you can."
    assert problems(draft, values, customer) == []
    body = draft
    for key, value in values.items():
        body = body.replace(f"[{key}]", value)
    assert check_final(body, values) == []
    assert "says booked" in problems(draft.replace("get it booked", "it is already booked"), values, customer)
