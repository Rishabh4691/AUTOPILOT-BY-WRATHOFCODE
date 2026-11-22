"""Portal outage (rounds 93-97): price portal airlines from portal prices seen earlier."""

from decimal import Decimal as D
from pathlib import Path

from sourcing import portal_cache as pc


def seen(tmp_path: Path, rows) -> Path:
    path = tmp_path / "cache.jsonl"
    for origin, dest, airline, kg, total, days, breaks in rows:
        pc.record(origin, dest, airline, airline[:2].upper(), D(kg), D(total), "EUR", days, breaks, path=path)
    return path


def test_same_break_is_priced_exactly(tmp_path: Path) -> None:
    # all-in per kg 2.00 in the 1000+ break -> 1136 kg = 2272.00
    path = seen(tmp_path, [("DUS", "MEX", "Xenon Cargo Airlines", "1500", "3000.00", 2, ())])
    [e] = pc.estimate("DUS", "MEX", D("1136"), path=path)
    assert e["airline"] == "Xenon Cargo Airlines" and e["total"] == D("2272.00") and e["transit_days"] == 2


def test_other_break_is_never_guessed(tmp_path: Path) -> None:
    path = seen(tmp_path, [("DUS", "MEX", "Xenon Cargo Airlines", "211", "927.95", 2, ())])
    assert pc.estimate("DUS", "MEX", D("1136"), path=path) == []


def test_next_break_up_is_used_when_cheaper(tmp_path: Path) -> None:
    # 950 kg in the 500 break at 2.50/kg = 2375; next break 1000 kg at 2.20/kg = 2200 -> 2200
    path = seen(tmp_path, [("FRA", "ORD", "Lumen", "800", "2000.00", 1, ()),
                           ("FRA", "ORD", "Lumen", "1200", "2640.00", 1, ())])
    [e] = pc.estimate("FRA", "ORD", D("950"), path=path)
    assert e["total"] == D("2200.00")


def test_airline_breaks_win_over_known_breaks(tmp_path: Path) -> None:
    # this airline breaks at 300, not 250: 260 and 290 are the same break
    path = seen(tmp_path, [("HAM", "SGN", "Nova", "290", "870.00", 4, (D(100), D(300), D(500)))])
    [e] = pc.estimate("HAM", "SGN", D("260"), path=path)
    assert e["total"] == D("780.00")


def test_small_weights_are_not_estimated(tmp_path: Path) -> None:
    # under 100 kg the minimum charge can apply, so price per kg is not constant
    path = seen(tmp_path, [("CGN", "DFW", "Lumen", "85", "457.08", 1, ())])
    assert pc.estimate("CGN", "DFW", D("70"), path=path) == []


def test_unknown_lane_and_broken_file(tmp_path: Path) -> None:
    path = tmp_path / "cache.jsonl"
    path.write_text('not json\n{"origin": "X"}\n')
    assert pc.estimate("DUS", "MEX", D("500"), path=path) == []
    assert pc.estimate("DUS", "MEX", D("500"), path=tmp_path / "missing.jsonl") == []


def test_round_122_newest_dataset_wins(tmp_path: Path) -> None:
    """Tamarind FRA-LOS: 3.95 EUR/kg in an older dataset, 4.47 in the current one."""
    path = tmp_path / "cache.jsonl"
    pc.record("FRA", "LOS", "Tamarind Airways", "TM", D("1075"), D("4246.25"), "EUR", 3, path=path, dataset="v2")
    pc.record("FRA", "LOS", "Tamarind Airways", "TM", D("1378"), D("6158.54"), "EUR", 3, path=path, dataset="v3")
    pc.record("DUS", "JFK", "Fjordline Air Cargo", "FQ", D("127"), D("433.07"), "EUR", 3, path=path, dataset="v3")
    [e] = pc.estimate("FRA", "LOS", D("1162"), path=path)
    assert e["dataset"] == "v3" and e["total"] == (D("6158.54") / D("1378") * D("1162")).quantize(D("0.01"))


def test_old_dataset_alone_is_not_used_once_a_newer_one_exists(tmp_path: Path) -> None:
    path = tmp_path / "cache.jsonl"
    pc.record("FRA", "LOS", "Tamarind Airways", "TM", D("1075"), D("4246.25"), "EUR", 3, path=path, dataset="v2")
    pc.record("DUS", "JFK", "Fjordline Air Cargo", "FQ", D("127"), D("433.07"), "EUR", 3, path=path, dataset="v3")
    assert pc.estimate("FRA", "LOS", D("1162"), path=path) == []  # only a stale price: no estimate
