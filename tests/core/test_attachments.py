from pathlib import Path

from core.agents.attachments import dangerous_goods, to_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_packing_list_xlsx_reveals_un1133() -> None:
    text = to_text("PL_53839.xlsx", (FIXTURES / "PL_53839.xlsx").read_bytes())
    assert "industrial adhesives" in text
    assert dangerous_goods(text) is not None
    assert "UN1133" in (dangerous_goods(text) or "")


def test_non_dangerous_wording_is_not_flagged() -> None:
    body = "The goods are general cargo, non-dangerous. Dangerous goods: no. 715 kg, 2.65 cbm."
    assert dangerous_goods(body) is None


def test_un_number_in_body_is_flagged() -> None:
    assert dangerous_goods("Lithium batteries UN 3480 packed alone") == "UN3480"
