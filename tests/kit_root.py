"""Where the start kit lives for tests.

The kit zip unpacks to data/kit/start-kit/, KIT_DIR can point elsewhere, and a
trimmed copy is committed under tests/core/fixtures/kit. The loaders in
mail.kit search a folder recursively, so any of these folders works. The old
check looked only for data/kit/carrier-list.csv and skipped about 50 tests
on every machine where the kit was unpacked normally.
"""

from pathlib import Path

import pytest

from mail.config import ROOT, settings

FIXTURE_KIT = Path(__file__).parent / "core" / "fixtures" / "kit"


def find_kit() -> Path | None:
    for folder in (settings.kit_dir, ROOT / "data" / "kit", FIXTURE_KIT):
        if folder.exists() and next(folder.rglob("carrier-list.csv"), None):
            return folder
    return None


KIT = find_kit() or ROOT / "data" / "kit"
needs_kit = pytest.mark.skipif(find_kit() is None, reason="start kit not found")
