from pathlib import Path

from core.agents.directory import load_directory

KIT = Path(__file__).parent / "fixtures" / "kit"


def test_directory_loads_airlines_truckers_and_zones() -> None:
    directory = load_directory(KIT)
    assert len(directory.airlines()) == 29
    assert directory.by_email("Yellowtail-Air-Freight@hackloop.mail") is not None
    assert {c.name for c in directory.truckers_for_zone("45")} >= {
        "Taunusfracht",
        "Grautal Trucking",
    }
    zone = directory.zone("80")
    assert zone is not None and zone.airport == "MUC"
    assert any(c.name == "Yellowtail Air Freight" for c in directory.airlines_serving("syd"))
