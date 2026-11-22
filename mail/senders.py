"""Lookalike senders: an address that copies a known customer's but differs in its separators.

Rounds 160 and 173 (2026-11-22) brought "weidner.spielwaren@hackloop.mail" and
"auer.maschinenbau@hackloop.mail" next to the real "weidner-spielwaren@..." and
"auer-maschinenbau@...", asking for the offer to be sent to the new address. They were ignored
only because they were not quote requests; a lookalike sending a full request, or replying
"yes, please book" in a thread, would have been answered.
"""

from __future__ import annotations

import re

SEPARATORS = re.compile(r"[.\-_+]")


def _parts(address: str) -> tuple[str, str]:
    local, _, domain = (address or "").strip().lower().partition("@")
    return local, domain


def same_address(a: str, b: str) -> bool:
    return (a or "").strip().lower() == (b or "").strip().lower()


def lookalike_of(sender: str, known: set[str] | list[str]) -> str | None:
    """The known customer address that `sender` imitates, or None.

    Same domain, and the local parts are equal once dots, hyphens, underscores and plus signs are
    removed, but the addresses themselves differ.
    """
    local, domain = _parts(sender)
    if not local or not domain:
        return None
    flat = SEPARATORS.sub("", local)
    for other in known:
        o_local, o_domain = _parts(other)
        if o_domain == domain and o_local != local and SEPARATORS.sub("", o_local) == flat:
            return other.strip().lower()
    return None
