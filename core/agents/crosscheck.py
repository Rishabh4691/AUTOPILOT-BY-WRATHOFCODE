from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from typing import Any

from core.contracts import RFQ, Agent, EventStatus, Mail
from core.pricing.weight import volume_cbm
from mail import gateway
from mail.text import fresh_text

log = logging.getLogger("core.crosscheck")

MODEL = "gpt-4.1"
TOLERANCE = Decimal("0.05")
PROMPT = """Read this air freight request and its attached documents. Work it out, then return only one JSON
object with final numbers (no formulas, no explanation):
{{"gross_kg": number, "volume_cbm": number or null, "pieces": integer or null}}
Rules: total GROSS weight of the whole shipment in kg (never net weight; add up all lots and
multiply 'each' figures by the piece count). Total volume in cbm (from the stated total or from
dimensions). If the mail and an attached packing document disagree, use the document. Ignore
quoted or forwarded older messages.

MAIL:
{mail}

DOCUMENTS:
{docs}"""


def _arith(expr: str) -> Decimal | None:
    import ast
    import operator

    ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return Decimal(str(node.value))
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](walk(node.left), walk(node.right))
        raise ValueError("not plain arithmetic")

    try:
        return walk(ast.parse(expr.strip(), mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, ArithmeticError):
        return None


def read_numbers(text: str) -> dict:
    for block in reversed(re.findall(r"\{[^{}]*\}", text or "", re.S)):
        try:
            data = json.loads(block)
            if data.get("gross_kg") is not None:
                return data
        except ValueError:
            pass
    out: dict = {}
    for key in ("gross_kg", "volume_cbm", "pieces"):
        found = re.findall(rf'"{key}"\s*:\s*([0-9().+\-*/ ]+?)\s*(?:,|\n|\}})', text or "")
        for expr in reversed(found):
            value = _arith(expr)
            if value is not None:
                out[key] = value
                break
    return out


def tricky(mail: Mail) -> bool:
    text = fresh_text(mail.body)
    weights = re.findall(r"\d[\d.,]*\s*(?:kg|kgs|lbs?)\b", text, re.I)
    return bool(mail.attachments) or len(weights) > 1 or bool(re.search(r"\blot\s*\d", text, re.I))


def differs(a: Decimal | None, b: Decimal | None) -> bool:
    if a is None or b is None or b == 0:
        return False
    return abs(a - b) / b > TOLERANCE


def lots_agree(mail: Mail, rfq: RFQ) -> bool:
    """The code's own lot parser read the lot lines and its totals are what was extracted.

    Rounds 153, 158 and 183: one consignment in three "Lot N:" lines. The code's totals were right
    each time (423 kg / 1.895 cbm, 1797 kg / 15.278 cbm, 1898 kg / 15.339 cbm); the gpt-4.1 second
    reader got them wrong, held the quote and cost a model call. When the lot parser agrees with
    the extraction, the second reader is not asked.
    """
    from mail.extract import parse_lots

    if mail.attachments:
        return False
    try:
        lots = parse_lots(fresh_text(mail.body))
    except Exception:
        return False
    if not lots or lots[1] <= 0:
        return False
    ours_cbm = rfq.volume_cbm if rfq.volume_cbm is not None else (volume_cbm(rfq.pieces) if rfq.pieces else None)
    same_kg = not differs(lots[1], rfq.gross_kg)
    same_cbm = lots[2] == 0 or ours_cbm is None or not differs(lots[2], ours_cbm)
    return same_kg and same_cbm


async def cross_check(orch: Any, mail: Mail, rfq: RFQ, attachments=None) -> None:
    if not tricky(mail):
        return
    if lots_agree(mail, rfq):
        orch.emit(
            Agent.RFQ, "cross_check", EventStatus.OK,
            f"Lot lines of request {mail.id} read by the code: {rfq.gross_kg} kg, {rfq.volume_cbm} cbm.",
            mail.id,
        )
        return
    try:
        docs = ""
        if attachments is not None and mail.attachments:
            docs = "\n\n".join(t for _, t in await attachments(mail) if t)[:6000]
        prompt = PROMPT.format(mail=fresh_text(mail.body)[:4000], docs=docs or "(none)")
        reply = await gateway.chat(
            [{"role": "user", "content": prompt}], max_tokens=300, model=MODEL, timeout=15
        )
        data = read_numbers(reply.text)
    except Exception as error:
        log.warning("cross_check_failed", extra={"rfq": mail.id, "error": type(error).__name__})
        return
    second_kg = Decimal(str(data["gross_kg"])) if data.get("gross_kg") else None
    second_cbm = Decimal(str(data["volume_cbm"])) if data.get("volume_cbm") else None
    ours_cbm = (
        rfq.volume_cbm
        if rfq.volume_cbm is not None
        else (volume_cbm(rfq.pieces) if rfq.pieces else None)
    )
    problems = []
    if differs(second_kg, rfq.gross_kg):
        problems.append(f"gross {rfq.gross_kg} kg vs {second_kg} kg")
    if differs(second_cbm, ours_cbm):
        problems.append(f"volume {ours_cbm} cbm vs {second_cbm} cbm")
    orch.emit(
        Agent.RFQ,
        "cross_check",
        EventStatus.HOLD if problems else EventStatus.OK,
        (
            f"Check the numbers for request {mail.id}: code read {'; '.join(problems)} (second reader). Take over if the code is wrong."
            if problems
            else f"Second reader agrees on request {mail.id}: {rfq.gross_kg} kg, {ours_cbm} cbm."
        ),
        mail.id,
        cost=Decimal(str(reply.cost_usd)),
    )
