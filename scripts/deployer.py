import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "bot.log"
STOP = ROOT / "data" / "STOP"
DB = ROOT / "data" / "app.db"
IN_FLIGHT = ("NEW", "EXTRACTED", "SOURCING", "PRICED")
CHECK_EVERY_S = 30
MAX_DEFER_S = 300


def note(level: str, message: str) -> None:
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "level": level,
        "logger": "deployer",
        "msg": message,
    }
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def bot_env() -> dict[str, str]:
    env = dict(os.environ)
    env["DRY_RUN"] = "0"
    env["PYTHONUTF8"] = "1"
    return env


def start_bot() -> subprocess.Popen[bytes]:
    STOP.unlink(missing_ok=True)
    handle = LOG.open("ab")
    process = subprocess.Popen(
        [sys.executable, "-m", "uv", "run", "python", "-m", "core.main"],
        cwd=ROOT,
        env=bot_env(),
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    note("info", f"deployer started bot pid {process.pid} at {head()[:7]}")
    return process


def stop_bot(process: subprocess.Popen[bytes] | None) -> None:
    STOP.touch()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            break
        if process is None and not other_bot_running():
            break
        time.sleep(0.5)
    STOP.unlink(missing_ok=True)


def other_bot_running() -> bool:
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "@(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*core.main*' "
            "-and $_.Name -eq 'python.exe' }).Count",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip() not in ("", "0")


def head() -> str:
    return git("rev-parse", "HEAD").stdout.strip()


def rfqs_in_flight() -> int:
    if not DB.exists():
        return 0
    cutoff = time.time() - 360
    with sqlite3.connect(DB, timeout=5) as db:
        marks = ",".join("?" for _ in IN_FLIGHT)
        row = db.execute(
            f"select count(*) from rfqs where status in ({marks}) and received_at > ?",
            (*IN_FLIGHT, cutoff),
        ).fetchone()
    return int(row[0]) if row else 0


def remote_head() -> str:
    if git("fetch", "-q", "origin").returncode != 0:
        note("warning", "deployer could not fetch origin")
        return ""
    return git("rev-parse", "origin/main").stdout.strip()


def is_new(remote: str) -> bool:
    return bool(remote) and git("merge-base", "--is-ancestor", remote, "HEAD").returncode != 0


def merge_remote() -> bool:
    if git("merge", "--ff-only", "origin/main").returncode == 0:
        return True
    merged = git("merge", "--no-edit", "origin/main")
    if merged.returncode == 0:
        return True
    git("merge", "--abort")
    note("error", "deployer could not merge origin/main, a conflict needs a person")
    return False


def tests_pass() -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "uv", "run", "pytest", "-q", "-x", "tests/core"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=240,
    )
    summary = (result.stdout.strip().splitlines() or ["no output"])[-1]
    note("info" if result.returncode == 0 else "error", f"deployer tests: {summary}")
    return result.returncode == 0


def main() -> int:
    process: subprocess.Popen[bytes] | None = None
    if other_bot_running():
        note("info", "deployer is taking over the running bot")
        stop_bot(None)
    process = start_bot()
    pending_since: float | None = None
    last_good = head()
    rejected = ""
    while True:
        time.sleep(CHECK_EVERY_S)
        if process.poll() is not None and not STOP.exists():
            note("error", f"bot exited with {process.returncode}, restarting")
            process = start_bot()
            continue
        remote = remote_head() if pending_since is None else ""
        if remote and remote != rejected and is_new(remote):
            if not merge_remote():
                rejected = remote
                continue
            if not tests_pass():
                note("error", f"deployer kept {last_good[:7]} running, {remote[:7]} fails tests")
                git("reset", "--hard", last_good)
                rejected = remote
                continue
            pending_since = time.monotonic()
        if pending_since is not None:
            busy = rfqs_in_flight()
            waited = time.monotonic() - pending_since
            if busy and waited < MAX_DEFER_S:
                continue
            note("info", f"deployer restarting bot for {head()[:7]} (in flight: {busy})")
            stop_bot(process)
            process = start_bot()
            last_good = head()
            pending_since = None


if __name__ == "__main__":
    sys.exit(main())
