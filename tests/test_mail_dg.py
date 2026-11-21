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


def test_special_cargo_words():
    from mail.dg import special_cargo

    assert "vaccines" in special_cargo("2 boxes of vaccines, keep +2 to +8 C")
    assert special_cargo("printed marketing material") == []


def test_scanned_packing_list_is_read(tmp_path):
    import shutil

    import pytest
    from PIL import Image, ImageDraw

    if shutil.which("tesseract") is None:
        pytest.skip("tesseract not installed")
    img = Image.new("RGB", (900, 120), "white")
    ImageDraw.Draw(img).text((10, 40), "Dangerous goods: UN1263 Class 3 Paint", fill="black")
    buf = tmp_path / "scan.png"
    img.save(buf)
    from mail.dg import attachment_text

    text = attachment_text("scan.png", buf.read_bytes())
    assert check("see attached", [("scan.png", text)]).dangerous


import httpx  # noqa: E402
import pytest  # noqa: E402

from mail.dg import write_docs_request  # noqa: E402

GOOD_DOCS = """Hi [FIRST],

thanks for the details on [REF]. Your packing list shows UN1133, class 3, so this flies as dangerous goods.
Could you send the Shipper's Declaration for Dangerous Goods and the safety data sheet (SDS)?
Please include UN number, proper shipping name, class, packing group and net quantity per package.
As soon as I have them you'll get one all-in price.

Cheers,
Lena
WRATHOFCODE Air Freight"""


def gw(text=None, status=200):
    def handler(req):
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": text}}],
                                         "usage": {"prompt_tokens": 300, "completion_tokens": 120}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


UN1133 = check("adhesives", [("pl.xlsx", "Dangerous goods: UN1133, Class 3")])


async def test_docs_request_uses_one_llm_call():
    body, cost, used, why = await write_docs_request(UN1133, "en", "Klaus", "WOC-2268", "Lena", "WRATHOFCODE Air Freight", http=gw(GOOD_DOCS))
    assert used and cost > 0 and why is None
    assert body.startswith("Hi Klaus,") and "WOC-2268" in body and "UN1133" in body


@pytest.mark.parametrize("bad", [GOOD_DOCS.replace("UN1133, ", ""), GOOD_DOCS.replace("one all-in price", "EUR 900")])
async def test_bad_docs_draft_falls_back_but_still_counts_the_call(bad):
    body, cost, used, why = await write_docs_request(UN1133, "en", "Klaus", "WOC-2268", "Lena", "WRATHOFCODE Air Freight", http=gw(bad))
    assert used and cost > 0 and why
    assert "UN1133" in body and "EUR" not in body


async def test_gateway_down_sends_template():
    body, cost, used, why = await write_docs_request(UN1133, "en", "Klaus", "WOC-2268", "Lena", "WRATHOFCODE Air Freight", http=gw(status=503))
    assert not used and cost == 0 and "Shipper's Declaration" in body


import pytest as _pytest  # noqa: E402


@_pytest.mark.parametrize("value", ["Not restricted", "Not applicable", "Non-DG", "non hazardous", "General cargo", "NR", "Kein Gefahrgut", "No"])
def test_negative_dg_fields_are_not_dangerous(value):
    assert not check("5 pieces of furniture samples", [("SLI.pdf", f"Goods description: furniture samples\nDangerous goods: {value}")]).dangerous


def test_live_round_33_not_restricted_is_not_dg():
    text = "Goods description: furniture samples\nTotal pieces: 5\nDangerous goods: Not restricted"
    assert not check("It's 5 pieces of furniture samples, 292 kg.", [("SLI_53351.pdf", text)]).dangerous
    assert check("adhesives", [("PL.xlsx", "Dangerous goods: UN1133, Class 3, Adhesives")]).dangerous
