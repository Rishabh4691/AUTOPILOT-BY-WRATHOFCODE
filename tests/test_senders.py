"""Lookalike senders (phishing, 2026-11-22 rounds 160 and 173)."""

import pytest

from mail.senders import lookalike_of, same_address

KNOWN = {"weidner-spielwaren@hackloop.mail", "auer-maschinenbau@hackloop.mail", "nordlicht-audio@hackloop.mail"}


@pytest.mark.parametrize(
    "sender, real",
    [
        ("weidner.spielwaren@hackloop.mail", "weidner-spielwaren@hackloop.mail"),  # round 160
        ("auer.maschinenbau@hackloop.mail", "auer-maschinenbau@hackloop.mail"),  # round 173
        ("Nordlicht_Audio@hackloop.mail", "nordlicht-audio@hackloop.mail"),
        ("nordlichtaudio@hackloop.mail", "nordlicht-audio@hackloop.mail"),
    ],
)
def test_lookalikes_are_caught(sender, real):
    assert lookalike_of(sender, KNOWN) == real


@pytest.mark.parametrize(
    "sender",
    [
        "weidner-spielwaren@hackloop.mail",  # the customer itself
        "WEIDNER-SPIELWAREN@hackloop.mail",  # same address, other case
        "weidner-spielwaren@other.mail",  # other domain
        "kessler-feinmechanik@hackloop.mail",  # a different, new customer
    ],
)
def test_real_and_new_senders_pass(sender):
    assert lookalike_of(sender, KNOWN) is None


def test_same_address_ignores_case_and_spaces():
    assert same_address(" Auer-Maschinenbau@hackloop.mail ", "auer-maschinenbau@hackloop.mail")
    assert not same_address("auer.maschinenbau@hackloop.mail", "auer-maschinenbau@hackloop.mail")
