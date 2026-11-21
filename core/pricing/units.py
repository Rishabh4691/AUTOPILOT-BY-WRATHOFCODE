from decimal import Decimal, InvalidOperation

LB_TO_KG = Decimal("0.45359237")
INCH_TO_CM = Decimal("2.54")
IGNORED_CHARS = (" ", chr(0xA0), "'")


class UnitsError(ValueError):
    pass


def lb_to_kg(pounds: Decimal) -> Decimal:
    return pounds * LB_TO_KG


def inch_to_cm(inches: Decimal) -> Decimal:
    return inches * INCH_TO_CM


def _strip(text: str) -> str:
    raw = text.strip()
    for char in IGNORED_CHARS:
        raw = raw.replace(char, "")
    return raw


def _normalise(text: str) -> str:
    raw = _strip(text)
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            return raw.replace(".", "").replace(",", ".")
        return raw.replace(",", "")
    if raw.count(",") > 1:
        return raw.replace(",", "")
    if raw.count(",") == 1:
        head, tail = raw.split(",")
        if len(tail) == 3 and head.lstrip("-") not in ("", "0"):
            return head + tail
        return f"{head}.{tail}"
    if raw.count(".") > 1:
        return raw.replace(".", "")
    return raw


def parse_decimal(text: str) -> Decimal:
    try:
        value = Decimal(_normalise(text))
    except InvalidOperation as exc:
        raise UnitsError(f"not a number: {text!r}") from exc
    if not value.is_finite():
        raise UnitsError(f"not a finite number: {text!r}")
    return value
