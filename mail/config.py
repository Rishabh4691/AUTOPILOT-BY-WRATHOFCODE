import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path=ROOT / ".env"):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key, value.strip().strip("'\""))


load_env()


def _flag(name, default="0"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _path(value, default):
    p = Path(value or default)
    return p if p.is_absolute() else ROOT / p


@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv("FIVEU_API_KEY", "")
    base_url: str = os.getenv("FIVEU_BASE_URL", "https://api.start-hack.5u.ai").rstrip("/")
    gateway_url: str = os.getenv("FIVEU_GATEWAY_URL", "https://api.start-hack.5u.ai/v1/gateway").rstrip("/")
    our_address: str = os.getenv("OUR_ADDRESS", "wrathofcode@hackloop.mail").lower()
    rate_desk: str = os.getenv("RATE_DESK_ADDRESS", "ratedesk@hackloop.mail").lower()
    tracking_desk: str = os.getenv("TRACKING_ADDRESS", "tracking@hackloop.mail").lower()
    dry_run: bool = _flag("DRY_RUN", "1")
    kill_switch: bool = _flag("KILL_SWITCH")
    llm_model: str = os.getenv("WRITER_MODEL") or "gpt-4.1"
    poll_seconds: float = float(os.getenv("POLL_INTERVAL_SECONDS") or 3)
    db_path: Path = _path(os.getenv("DB_PATH"), "data/app.db")
    kit_dir: Path = _path(os.getenv("KIT_DIR"), "data/kit")


settings = Settings()
