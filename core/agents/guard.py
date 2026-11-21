from __future__ import annotations

import base64
import re

SOCIAL = {
    "keys or passwords": r"\b(api[- ]?keys?|gateway[- ]?keys?|team[- ]?keys?|passwords?|passwort|mot de passe|contraseña|credentials?|login details|access tokens?|2fa|one[- ]time code|verification code)\b",
    "bank change": r"\b(new bank (?:account|details)|change(?:d)? (?:of )?(?:our )?bank|iban|swift|wire (?:the )?(?:money|payment|transfer)|bankverbindung (?:hat sich )?geändert|nouveau rib)\b",
    "gift cards": r"\b(gift ?cards?|itunes cards?|amazon vouchers?)\b",
    "secrecy and pressure": r"\b(keep (?:it|this) (?:between us|confidential|quiet)|don'?t (?:tell|loop|involve) anyone|tell no one|i'?m in a (?:board )?meeting and can'?t talk|sent from my phone.{0,40}urgent)\b",
    "outside contact": r"\b(whatsapp me|text me on|call me on my private|reply to my personal)\b",
}
SECRET_SHAPES = re.compile(r"\b(sk-[A-Za-z0-9_-]{20,}|FIVEU_API_KEY|OPENAI_API_KEY|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")


def social_engineering(subject: str, body: str) -> list[str]:
    text = f"{subject}\n{body}"
    found = [name for name, pattern in SOCIAL.items() if re.search(pattern, text, re.I)]
    asks_secret = "keys or passwords" in found and re.search(r"\b(send|share|forward|reply with|give)\b", text, re.I)
    if asks_secret or len(found) >= 2:
        return found
    return []


def leaks_secret(text: str, secrets: list[str]) -> bool:
    if SECRET_SHAPES.search(text or ""):
        return True
    return any(s and len(s) >= 8 and s in (text or "") for s in secrets)


def outgoing_leaks(subject: str, body: str, attachments: tuple[dict, ...], secrets: list[str]) -> bool:
    if leaks_secret(f"{subject}\n{body}", secrets):
        return True
    for a in attachments:
        try:
            raw = base64.b64decode(a.get("content_base64") or "")
        except (ValueError, TypeError):
            continue
        if leaks_secret(raw.decode("latin-1", "ignore"), secrets):
            return True
    return False
