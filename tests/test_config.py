"""Tests for opkssh_wrapper.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from opkssh_wrapper.config import (
    Config,
    ConfigError,
    _validate_key_path,
    _validate_positive_int,
    load_config,
)


class TestConfigDefaults:
    """Config defaults are sane when no file exists."""

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path / "nonexistent.toml")
        assert cfg == Config()

    def test_default_values(self) -> None:
        cfg = Config()
        assert cfg.key_ttl_hours == 24
        assert cfg.key_wait_timeout == 10
        assert cfg.login_timeout == 120
        assert cfg.ssh_path is None
        assert cfg.opkssh_path == "opkssh"
        assert cfg.key_path == Path("~/.ssh/id_ecdsa")
        assert cfg.aggressive_login is False


class TestConfigParsing:
    """Valid TOML is correctly loaded."""

    def test_full_config(self, tmp_path: Path) -> None:
        ssh_dir = Path("~/.ssh").expanduser().resolve()
        key_file = ssh_dir / "my_key"
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(
            f"key_ttl_hours = 12\n"
            f"key_wait_timeout = 5\n"
            f"login_timeout = 60\n"
            f'ssh_path = "/usr/bin/ssh"\n'
            f'opkssh_path = "/usr/local/bin/opkssh"\n'
            f'key_path = "{key_file}"\n'
            f"aggressive_login = true\n",
            encoding="utf-8",
        )
        cfg = load_config(cfg_file)
        assert cfg.key_ttl_hours == 12
        assert cfg.key_wait_timeout == 5
        assert cfg.login_timeout == 60
        assert cfg.ssh_path == "/usr/bin/ssh"
        assert cfg.opkssh_path == "/usr/local/bin/opkssh"
        assert cfg.key_path == key_file
        assert cfg.aggressive_login is True

    def test_partial_config_uses_defaults(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text("key_ttl_hours = 6\n", encoding="utf-8")
        cfg = load_config(cfg_file)
        assert cfg.key_ttl_hours == 6
        assert cfg.key_wait_timeout == 10  # default

    def test_malformed_toml_raises(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text("this is not [valid toml", encoding="utf-8")
        with pytest.raises(ConfigError, match="Failed to parse"):
            load_config(cfg_file)


class TestValidatePositiveInt:
    """_validate_positive_int rejects non-positive values."""

    def test_positive_value_passes(self) -> None:
        _validate_positive_int("key_ttl_hours", 1)  # should not raise

    def test_zero_raises(self) -> None:
        with pytest.raises(ConfigError, match="must be a positive integer"):
            _validate_positive_int("key_ttl_hours", 0)

    def test_negative_raises(self) -> None:
        with pytest.raises(ConfigError, match="must be a positive integer"):
            _validate_positive_int("login_timeout", -5)

    def test_error_message_includes_name_and_value(self) -> None:
        with pytest.raises(ConfigError, match="key_wait_timeout") as exc_info:
            _validate_positive_int("key_wait_timeout", 0)
        assert "0" in str(exc_info.value)


class TestTimeoutValidationInLoadConfig:
    """load_config rejects non-positive timeout values."""

    @pytest.mark.parametrize("field_name", ["key_ttl_hours", "key_wait_timeout", "login_timeout"])
    def test_zero_value_raises(self, tmp_path: Path, field_name: str) -> None:
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(f"{field_name} = 0\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="must be a positive integer"):
            load_config(cfg_file)

    @pytest.mark.parametrize("field_name", ["key_ttl_hours", "key_wait_timeout", "login_timeout"])
    def test_negative_value_raises(self, tmp_path: Path, field_name: str) -> None:
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(f"{field_name} = -1\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="must be a positive integer"):
            load_config(cfg_file)

    @pytest.mark.parametrize(
        "field_name,value",
        [("key_ttl_hours", 1), ("key_wait_timeout", 1), ("login_timeout", 1)],
    )
    def test_positive_value_accepted(self, tmp_path: Path, field_name: str, value: int) -> None:
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(f"{field_name} = {value}\n", encoding="utf-8")
        cfg = load_config(cfg_file)
        assert getattr(cfg, field_name) == value


class TestKeyPathValidation:
    """Key path must reside in ~/.ssh/ or ~/.opk/."""

    def test_valid_ssh_path(self) -> None:
        path = Path("~/.ssh/id_ecdsa")
        result = _validate_key_path(path)
        assert result == path.expanduser().resolve()

    def test_valid_opk_path(self, tmp_path: Path) -> None:
        opk_dir = Path("~/.opk").expanduser().resolve()
        opk_dir.mkdir(parents=True, exist_ok=True)
        path = Path("~/.opk/test_key")
        result = _validate_key_path(path)
        assert result == path.expanduser().resolve()

    def test_invalid_path_raises(self) -> None:
        with pytest.raises(ConfigError, match="outside allowed directories"):
            _validate_key_path(Path("/tmp/bad_key"))

    def test_traversal_attack_rejected(self) -> None:
        with pytest.raises(ConfigError, match="outside allowed directories"):
            _validate_key_path(Path("~/.ssh/../../etc/passwd"))

    def test_config_with_bad_key_path_raises(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(
            'key_path = "/tmp/bad_key"\n',
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="outside allowed directories"):
            load_config(cfg_file)
