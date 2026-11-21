from decimal import Decimal
from pathlib import Path

import pytest

from core.config import ConfigError, load_settings


def test_settings_default_to_dry_run(tmp_path: Path) -> None:
    settings = load_settings(tmp_path, {"FIVEU_API_KEY": "test-key"})
    assert settings.dry_run is True
    assert settings.kill_switch is False
    assert "test-key" not in repr(settings)


def test_missing_key_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_settings(tmp_path, {})


def test_env_file_is_read_and_environment_wins(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("FIVEU_API_KEY=from-file\nDRY_RUN=1\n")
    settings = load_settings(tmp_path, {"DRY_RUN": "0"})
    assert settings.api_key == "from-file"
    assert settings.dry_run is False


def test_new_defaults(tmp_path: Path) -> None:
    settings = load_settings(tmp_path, {"FIVEU_API_KEY": "test-key"})
    assert settings.llm_model == "gpt-5-nano"
    assert settings.llm_fallback_model == "gpt-4.1-mini"
    assert settings.llm_max_output_tokens == 250
    assert settings.llm_timeout_s == 12.0
    assert settings.volume_kg_per_cbm == Decimal("167")
    assert settings.price_weight == Decimal("0.5")
    assert settings.transit_weight == Decimal("0.5")
    assert (settings.send_at_s, settings.wait_until_s, settings.hard_stop_s) == (120, 240, 315)
    assert settings.body_char_limit == 4000


def test_env_overrides_new_settings(tmp_path: Path) -> None:
    settings = load_settings(
        tmp_path,
        {
            "FIVEU_API_KEY": "test-key",
            "LLM_MODEL": "custom",
            "VOLUME_KG_PER_CBM": "200",
            "PRICE_WEIGHT": "0.7",
            "TRANSIT_WEIGHT": "0.3",
            "LLM_MAX_OUTPUT_TOKENS": "100",
        },
    )
    assert settings.llm_model == "custom"
    assert settings.volume_kg_per_cbm == Decimal("200")
    assert settings.price_weight == Decimal("0.7")
    assert settings.transit_weight == Decimal("0.3")
    assert settings.llm_max_output_tokens == 100
