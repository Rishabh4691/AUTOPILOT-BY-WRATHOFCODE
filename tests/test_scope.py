"""Round 159 (accepted with a decline): an air import into Germany is out of scope."""

import pytest

from mail.scope import decline_body, import_into_germany

ROUND_159 = (
    "Hi,\n\nCould you quote an all-in price in EUR for an airport-to-airport air import from Tokyo airport "
    "(NRT), JP, to Hamburg airport (HAM), Germany? Our supplier will hand over the goods at NRT, and we're "
    "the receiver in Germany.\n\nThe furniture samples will be ready on 2026-11-26: 6 pieces, 1741 kg gross, "
    "12.61 cbm.\n\nThanks!\n\nMira Petersen"
)


def test_round_159_is_an_import_into_germany():
    assert import_into_germany("Air import quote: NRT to HAM", ROUND_159) == ("NRT", "HAM")
    assert import_into_germany("", ROUND_159) == ("NRT", "Hamburg")


@pytest.mark.parametrize(
    "subject, body",
    [
        # exports framed as the buyer's import: goods still leave Germany
        ("Fastest air freight to RUH", "Our buyer in Riyadh, SA, is importing electronic control units from us in "
         "Germany. Please quote the fastest option from DUS to RUH. We deliver them ourselves to DUS."),
        ("Air freight quote: MUC to SGN", "Could you quote the fastest option from MUC to SGN? The shipment will be "
         "ready on 2026-11-29, and we'll deliver it to MUC ourselves."),
        ("RE: FW: VIENNA AIRPORT - LAX / 32 PLT", "Could you please quote the fastest air freight option to DXB "
         "(Dubai, AE)? We will deliver the shipment to MUC ourselves."),
        ("Air freight quote to NBO", "Please quote to NBO (Nairobi, KE), all-in in EUR, including truck pickup "
         "from our site at 36241 (Fulda), Germany, to the airport."),
    ],
)
def test_exports_are_not_imports(subject, body):
    assert import_into_germany(subject, body) is None


def test_decline_names_the_route_and_reference():
    text = decline_body("NRT", "HAM", "WOC-47995")
    assert "only handle air exports" in text and "NRT into HAM" in text and "WOC-47995" in text


ROUND_177 = (
    "Hi there,\n\nHope your week's going well! Could you send me an all-in price in EUR for a port-to-port sea freight "
    "shipment from Hamburg (DEHAM) to Jebel Ali (AEJEA)?\n\nThe furniture samples will be ready on 2026-11-27. It's an "
    "FCL shipment in 1 x 40ft container, with 6 pieces, a gross weight of 9617 kg and a total volume of 43.5 cbm.\n\n"
    "Cheers,\nKlaus Weidner"
)


def test_round_177_sea_freight_is_out_of_scope():
    from mail.scope import sea_decline_body, sea_freight

    assert sea_freight("Sea freight quote: Hamburg to Jebel Ali", ROUND_177)
    text = sea_decline_body("WOC-53359")
    assert "only handle air freight exports" in text and "WOC-53359" in text


@pytest.mark.parametrize(
    "body",
    [
        "We need air freight for this, sea freight is too slow. 2 pallets, 400 kg, from FRA to JFK.",
        "Please quote the cheapest air freight option from MUC to SGN, 3 pieces, 820 kg, 4.1 cbm.",
    ],
)
def test_air_requests_are_not_sea_freight(body):
    from mail.scope import sea_freight

    assert not sea_freight("Air freight quote", body)
