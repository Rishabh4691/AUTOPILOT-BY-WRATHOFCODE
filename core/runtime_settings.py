"""Settings the Control Room can change while the bot runs (data/settings.json)."""

import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ("gpt-4.1-mini", "gpt-4.1")
DEFAULTS = {"writer_model": None, "daily_updates": False}
_lock = threading.Lock()
_cache: dict = {"mtime": None, "data": dict(DEFAULTS)}


def path() -> Path:
    return Path(os.environ.get("RUNTIME_SETTINGS_PATH") or ROOT / "data" / "settings.json")


def load() -> dict:
    target = path()
    try:
        mtime = target.stat().st_mtime
    except OSError:
        return dict(DEFAULTS)
    if mtime != _cache["mtime"]:
        try:
            data = json.loads(target.read_text())
        except (OSError, ValueError):
            data = {}
        _cache.update(mtime=mtime, data={**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}})
    return dict(_cache["data"])


def save(changes: dict) -> dict:
    clean = {k: v for k, v in changes.items() if k in DEFAULTS}
    if "writer_model" in clean and clean["writer_model"] not in (*MODELS, None):
        raise ValueError("unknown model")
    if "daily_updates" in clean:
        clean["daily_updates"] = bool(clean["daily_updates"])
    with _lock:
        data = {**load(), **clean}
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(target)
    return data


def writer_model() -> str | None:
    model = load().get("writer_model")
    return model if model in MODELS else None


def daily_updates() -> bool:
    return bool(load().get("daily_updates"))
