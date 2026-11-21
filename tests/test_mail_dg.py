from pathlib import Path

from mail.dg import attachment_text, check, docs_request

FIX = Path(__file__).parent / "core" / "fixtures" / "attachments"
ROUND_10 = (
    "Could you send me an all-in price in EUR for the cheapest air freight option to GRU? "
    "It's 3 pieces of industrial adhesives, with a gross weight of 715 kg and a total volume of 2.65 cbm. "
    "The goods are general cargo, non-dangerous, and I've attached our packing specification."
)


def test_live_round_10_attachment_says_un1133_although_mail_says_non_dangerous():
    text = attachment_text("PL_53839.xlsx", (FIX / "PL_53839.xlsx").read_bytes())
    assert "UN1133" in text
    result = check(ROUND_10, [("PL_53839.xlsx", text)])
    assert result.dangerous and result.un_numbers == ["1133"] and "3" in result.classes
    assert not result.docs_attached


def test_adhesives_alone_raise_the_flag():
    assert check("3 pieces of industrial adhesives, 715 kg, general cargo", []).dangerous


def test_plain_cargo_is_not_dangerous():
    assert not check("12 pieces of printed marketing material, 676 kg gross and 5.79 cbm.", []).dangerous
    assert not check("Lot 1: 4 cartons of automotive sensors", [("pl.csv", "Dangerous goods: no\nItem: sensors")]).dangerous


def test_documents_attached_means_no_request():
    result = check("UN1263 paint, 200 kg", [("MSDS_paint.pdf", ""), ("DGD_2041.pdf", "")])
    assert result.dangerous and result.docs_attached


def test_docs_request_text():
    result = check(ROUND_10, [("PL_53839.xlsx", "Dangerous goods: UN1133, Class 3, Adhesives")])
    body = docs_request(result, "en", "Klaus", "WOC-2268", "Lena", "WRATHOFCODE Air Freight")
    assert body.startswith("Hi Klaus,") and "UN1133, class 3" in body
    assert "Shipper's Declaration for Dangerous Goods" in body and "EUR" not in body
    assert "—" not in body and "–" not in body
