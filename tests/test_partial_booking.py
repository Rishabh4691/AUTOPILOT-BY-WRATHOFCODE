import pytest

from mail.multilot import chosen_lots, partial_acceptance

LANES = ["SGN", "ICN"]


@pytest.mark.parametrize(
    "text, want",
    [
        ("Thanks for your offer. We're happy to go ahead with both shipments. Please book only the first "
         "shipment for now. We'll confirm the second shipment later. Thanks", [0]),
        ("Please book only the ICN shipment.", [1]),
        ("Book lot B only, hold lot A.", [1]),
        ("Please book only the first one and hold the second.", [0]),
        ("Go ahead with SGN only, not ICN.", [0]),
        ("Please book both.", []),
        ("We will book later, hold both for now.", []),
    ],
)
def test_which_shipments_a_partial_yes_books(text: str, want: list[int]) -> None:
    assert chosen_lots(text, LANES) == want


def test_round_127_reply_is_a_partial_yes() -> None:
    text = ("We're happy to go ahead with both shipments. Please book only the first shipment for now. "
            "We'll confirm the second shipment later.")
    assert partial_acceptance(text)
