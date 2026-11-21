"""Round 33 (MUC-CAI, furniture samples): lost as too_low. Three causes, all fixed here."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path

from core.agents.extractor import RegexRfqExtractor
from core.agents.mailbox import parse_mail
from core.agents.rules_extractor import RulesFirstExtractor, document_totals
from core.config import load_settings
from core.pricing.weight import chargeable_kg
from mail.dg import check

FIXTURE = Path(__file__).parent / "fixtures" / "mail" / "real_rfq_8501.json"
# Text of the attached SLI_53351.pdf, as pdfplumber reads it.
SLI = (
    "Packing Specification\nNo. 53351\nDate: 2026-11-27\n"
    "Shipper: Hofmann Textilwerk KG, Bielefeld, Germany\nConsignee: Cairo Imports Ltd., Cairo, EG\n"
    "Destination airport: CAI\nGoods description: furniture samples\nTotal pieces: 5\n"
    "Total gross weight (kg): 292\nTotal volume (cbm): 1.92\nDangerous goods: Not restricted\n"
    "Gross weight (kg) Width (cm) Length (cm) Height (cm) Pieces\n292 40 120 80 5"
)


def extractor(texts):
    async def attachments(mail):
        return texts

    settings = load_settings(environ={"FIVEU_API_KEY": "k"})
    return RulesFirstExtractor(RegexRfqExtractor(settings, None), attachments=attachments)


def test_not_restricted_is_not_dangerous_goods() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert not check(raw["body"], [("SLI_53351.pdf", SLI)]).dangerous
    assert check("x", [("sli.pdf", "Dangerous goods: UN1950, Class 2.1, Aerosols")]).dangerous


def test_each_piece_dimensions_count_all_five_pieces() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rfq, _ = asyncio.run(extractor([]).extract(parse_mail(dict(raw, attachments=[]))))
    assert sum(p.count for p in rfq.pieces) == 5  # was 1: "Each piece measures 120 x 40 x 116 cm"


def test_packing_document_totals_win_over_the_mail_text() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rfq, _ = asyncio.run(extractor([("SLI_53351.pdf", SLI)]).extract(parse_mail(raw)))
    assert rfq.volume_cbm == Decimal("1.92") and rfq.gross_kg == Decimal("292")
    assert "pieces: 5" in rfq.notes
    assert chargeable_kg(rfq.gross_kg, rfq.pieces, rfq.volume_cbm) == Decimal("321.0")


def test_document_totals_reads_shuffled_xlsx_labels() -> None:
    text = ("Total pieces: 3 Total gross weight (kg): 715 Total volume (cbm): 2.65 "
            "Dangerous goods: UN1133, Class 3, Adhesives")
    assert document_totals(text) == {"pieces": 3, "gross_kg": Decimal("715"), "volume_cbm": Decimal("2.65")}
