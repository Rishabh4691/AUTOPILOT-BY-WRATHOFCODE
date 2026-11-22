"""Preferences written in non-Latin scripts and Turkish (round 149: Korean fastest read as cheapest)."""

import pytest

from mail.extract import extract

BASE = "Pickup at our site 36030 Fulda, Germany, to KUL (Kuala Lumpur, MY). 12 pieces, 1271 kg, 4.26 cbm, ready 2026-11-27. "


@pytest.mark.parametrize(
    "wish, pref",
    [
        ("KUL(Kuala Lumpur, MY)까지 가장 빠른 옵션으로 견적 부탁드립니다.", "fastest"),
        ("가장 저렴한 옵션으로 견적 부탁드립니다.", "cheapest"),
        ("请报最快的方案。", "fastest"),
        ("请报最便宜的方案。", "cheapest"),
        ("一番早い便でお願いします。", "fastest"),
        ("En hızlı seçeneği istiyoruz.", "fastest"),
        ("En ucuz seçeneği istiyoruz.", "cheapest"),
    ],
)
def test_preference_in_other_scripts(wish, pref):
    x = extract("Air freight quote to KUL", BASE + wish, "c@hackloop.mail", "1")
    assert x.preference == pref and x.preference_stated
