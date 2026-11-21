import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY_PATTERN = re.compile(r"\b(hk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})")
SKIPPED = {"scripts/scan_secrets.sh"}
GIT = shutil.which("git") or "git"


def tracked_files() -> list[str]:
    result = subprocess.run(
        [GIT, "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True, text=True
    )
    return [name for name in result.stdout.split("\0") if name and name not in SKIPPED]


def test_no_key_like_string_is_tracked() -> None:
    offenders = []
    for name in tracked_files():
        path = ROOT / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if KEY_PATTERN.search(text):
            offenders.append(name)
    assert offenders == [], f"key-like strings tracked in: {offenders}"
