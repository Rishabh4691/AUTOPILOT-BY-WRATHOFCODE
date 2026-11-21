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


def _mail(body: str, attachments: bool = True):
    return parse_mail(
        {
            "id": 9101,
            "from": "kunde@customer.mail",
            "to": "wrathofcode@hackloop.mail",
            "subject": "Quote request",
            "body": body,
            "in_reply_to": None,
            "references": [],
            "received_at": "2026-11-21T10:00:00+00:00",
            "attachments": [{"id": 1, "filename": "packing_list.xlsx"}] if attachments else [],
        }
    )


def test_document_gross_with_thousands_comma_is_not_a_decimal() -> None:
    assert document_totals("Total gross weight (kg): 1,518")["gross_kg"] == Decimal("1518")
    assert document_totals("Total gross weight (kg): | 3,498")["gross_kg"] == Decimal("3498")
    assert document_totals("Total gross weight (kg): 12,5")["gross_kg"] == Decimal("12.5")


def test_document_totals_read_other_label_styles() -> None:
    cases = [
        ("TOTAL GROSS WEIGHT: 420,5 KG\nTOTAL VOLUME: 2.1 M3", "420.5", "2.1"),
        ("Total G.W.: 1,202 kgs\nTotal measurement: 1.44 cbm", "1202", "1.44"),
        ("Gesamtbruttogewicht (kg): 1.917,5\nGesamtvolumen (m³): 8,32", "1917.5", "8.32"),
        ("Gross weight total: 1202 kg\nVolume total: 1.095 m3", "1202", "1.095"),
        ("Poids brut total (kg) : 3147\nVolume total (m3) : 1,42", "3147", "1.42"),
        ("Total gross weight | 86 kg\nTotal volume | 0.47 m³", "86", "0.47"),
    ]
    for text, gross, cbm in cases:
        found = document_totals(text)
        assert found["gross_kg"] == Decimal(gross) and found["volume_cbm"] == Decimal(cbm), text


def test_site_unknown_ignores_a_po_number_but_not_a_postcode() -> None:
    body = (
        "Please quote to KUL. Please arrange pickup from our warehouse.\n"
        "3 pallets, 450 kg, 2.1 cbm.\nOur reference: PO 70247\nThanks,\nMarco"
    )
    rfq, _ = asyncio.run(extractor([]).extract(_mail(body, attachments=False)))
    assert "site_unknown" in rfq.notes
    with_postcode = body.replace("warehouse.", "warehouse, 61018 Bad Homburg.")
    rfq, _ = asyncio.run(extractor([]).extract(_mail(with_postcode, attachments=False)))
    assert "site_unknown" not in rfq.notes and rfq.pickup_postcode == "61018"


def test_document_volume_keeps_the_piece_count_from_the_mail() -> None:
    body = (
        "Please quote FRA to SYD.\n12 pallets 80x60x75 cm, total gross weight 132 kg.\n"
        "Thanks,\nMira"
    )
    doc = (
        "Commercial packing list\nTotal gross weight (kg): 132\nTotal volume (m3): 4.32\n"
        "DG: Not restricted"
    )
    rfq, _ = asyncio.run(extractor([("packing_list.xlsx", doc)]).extract(_mail(body)))
    assert rfq.volume_cbm == Decimal("4.32") and not rfq.pieces
    assert "pieces: 12" in rfq.notes


def test_currency_in_quoted_history_is_ignored() -> None:
    body = (
        "Please quote FRA to DOH, 3 pallets, 450 kg, 2.1 cbm.\nThanks,\nPiotr\n\n"
        "-----Original Message-----\nFrom: Sales <sales@forwarder.mail>\nSent: Monday\n\n"
        "Last time: 999 kg from MUC. Currency USD."
    )
    rfq, _ = asyncio.run(extractor([]).extract(_mail(body, attachments=False)))
    assert rfq.currency in (None, "EUR")


def test_document_totals_reads_double_colon_xlsx() -> None:
    # Round 35's xlsx: "Total gross weight (kg):: 1751" (mail text said 2644 kg).
    text = ("Total pieces:: 19\nTotal gross weight (kg):: 1751\nTotal volume (cbm):: 11.97\n"
            "Dangerous goods:: Not restricted")
    assert document_totals(text) == {"pieces": 19, "gross_kg": Decimal("1751"), "volume_cbm": Decimal("11.97")}
