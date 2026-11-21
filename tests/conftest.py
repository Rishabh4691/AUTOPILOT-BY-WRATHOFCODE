from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_customer_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep every test away from the bot's real data/customers.json."""
    from mail import extract

    monkeypatch.setattr(extract, "MEMORY_PATH", tmp_path / "customers.json")
    monkeypatch.setenv("CUSTOMER_MEMORY_PATH", str(tmp_path / "customers.json"))
    yield


@pytest.fixture(autouse=True)
def kit_folder(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point mail.kit at the kit tests can find (data/kit, KIT_DIR or the committed fixture)."""
    from mail import kit
    from tests.kit_root import find_kit

    found = find_kit()
    if found is not None:
        monkeypatch.setattr(kit, "settings", kit.settings.__class__(kit_dir=found))
    kit.carriers.cache_clear()
    kit.pickup_zones.cache_clear()
    yield
    kit.carriers.cache_clear()
    kit.pickup_zones.cache_clear()
