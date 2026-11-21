import csv
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
ENV_FILES = (".env",)


class ConfigError(RuntimeError):
    pass


def load_env(root: Path = ROOT, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    merged: dict[str, str] = {}
    for name in ENV_FILES:
        path = root / name
        if path.is_file():
            merged.update({k: v for k, v in dotenv_values(path).items() if v is not None})
    merged.update(os.environ if environ is None else environ)
    return merged


def _flag(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    return int(value)


def _float(value: str | None, default: float) -> float:
    if value is None or value.strip() == "":
        return default
    return float(value)


def _decimal(value: str | None, default: Decimal) -> Decimal:
    if value is None or value.strip() == "":
        return default
    return Decimal(value.strip())


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    base_url: str
    gateway_url: str
    kit_url: str
    our_address: str
    rate_desk_address: str
    tracking_address: str
    dry_run: bool
    kill_switch: bool
    llm_model: str
    poll_interval_s: float
    max_tokens_per_rfq: int
    db_path: Path
    kit_dir: Path
    rfq_lifetime_s: int = 360
    price_weight: Decimal = Decimal("0.5")
    transit_weight: Decimal = Decimal("0.5")
    volume_kg_per_cbm: Decimal = Decimal("167")
    llm_fallback_model: str = "gpt-4.1-mini"
    llm_max_output_tokens: int = 250
    llm_timeout_s: float = 12.0
    send_at_s: float = 120.0
    wait_until_s: float = 240.0
    hard_stop_s: float = 315.0
    body_char_limit: int = 4000


def load_settings(root: Path = ROOT, environ: Mapping[str, str] | None = None) -> Settings:
    env = load_env(root, environ)
    api_key = env.get("FIVEU_API_KEY", "").strip()
    if not api_key:
        raise ConfigError("FIVEU_API_KEY is missing from .env or the environment.")
    base_url = env.get("FIVEU_BASE_URL", "https://api.start-hack.5u.ai").rstrip("/")
    return Settings(
        api_key=api_key,
        base_url=base_url,
        gateway_url=env.get("FIVEU_GATEWAY_URL", f"{base_url}/v1/gateway").rstrip("/"),
        kit_url=env.get("FIVEU_KIT_URL", f"{base_url}/kit/start-kit.zip"),
        our_address=env.get("OUR_ADDRESS", "wrathofcode@hackloop.mail").strip().lower(),
        rate_desk_address=env.get("RATE_DESK_ADDRESS", "ratedesk@hackloop.mail").strip().lower(),
        tracking_address=env.get("TRACKING_ADDRESS", "tracking@hackloop.mail").strip().lower(),
        dry_run=_flag(env.get("DRY_RUN"), default=True),
        kill_switch=_flag(env.get("KILL_SWITCH"), default=False),
        llm_model=env.get("LLM_MODEL", "").strip() or "gpt-5-nano",
        # The mailbox allows one poll per 5 s (since ~21:14 UTC); polling faster locked us out.
        poll_interval_s=max(6.0, float(env.get("POLL_INTERVAL_SECONDS") or "6")),
        max_tokens_per_rfq=_int(env.get("MAX_TOKENS_PER_RFQ"), 3000),
        db_path=root / (env.get("DB_PATH") or "data/app.db"),
        kit_dir=root / (env.get("KIT_DIR") or "data/kit"),
        price_weight=_decimal(env.get("PRICE_WEIGHT"), Decimal("0.5")),
        transit_weight=_decimal(env.get("TRANSIT_WEIGHT"), Decimal("0.5")),
        volume_kg_per_cbm=_decimal(env.get("VOLUME_KG_PER_CBM"), Decimal("167")),
        llm_fallback_model=env.get("LLM_FALLBACK_MODEL", "").strip() or "gpt-4.1-mini",
        llm_max_output_tokens=_int(env.get("LLM_MAX_OUTPUT_TOKENS"), 250),
        llm_timeout_s=_float(env.get("LLM_TIMEOUT_SECONDS"), 12.0),
    )


def auth_headers(settings: Settings) -> dict[str, str]:
    return {"X-API-Key": settings.api_key}


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))
