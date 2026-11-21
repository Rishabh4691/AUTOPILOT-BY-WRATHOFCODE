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
