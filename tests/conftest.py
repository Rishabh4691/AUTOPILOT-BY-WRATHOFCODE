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
