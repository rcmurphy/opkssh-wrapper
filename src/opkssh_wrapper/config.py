"""Configuration loading from TOML file.

Reads ``~/.config/opkssh-wrapper/config.toml`` (if present) and provides
sensible defaults for every setting.

Security:
    The configuration file is user-owned and trusted.  No secrets are
    stored in it; key material lives in files with restricted permissions.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        msg = (
            "Python <3.11 requires the 'tomli' package. "
            "Install it with: pip install tomli"
        )
        raise ImportError(msg) from exc

from opkssh_wrapper.i18n import _

_DEFAULT_CONFIG_PATH = Path("~/.config/opkssh-wrapper/config.toml")
_DEFAULT_KEY_PATH = Path("~/.ssh/id_ecdsa")

# Allowed parent directories for key paths.
_ALLOWED_KEY_PARENTS: tuple[Path, ...] = (
    Path("~/.ssh").expanduser().resolve(),
    Path("~/.opk").expanduser().resolve(),
)


@dataclass(frozen=True)
class Config:
    """Immutable application configuration with sensible defaults."""

    key_ttl_hours: int = 24
    key_wait_timeout: int = 10
    login_timeout: int = 120
    ssh_path: str | None = None
    opkssh_path: str = "opkssh"
    key_path: Path = field(default_factory=lambda: _DEFAULT_KEY_PATH)
    aggressive_login: bool = False


class ConfigError(Exception):
    """Raised when the configuration file cannot be parsed."""


def _validate_key_path(path: Path) -> Path:
    """Resolve *path* and verify it sits inside an allowed directory.

    Raises:
        ConfigError: If the resolved path escapes the allowed directories.

    Security:
        Prevents directory-traversal attacks via a crafted ``key_path``
        value in the configuration file.
    """
    resolved = path.expanduser().resolve()
    for parent in _ALLOWED_KEY_PARENTS:
        try:
            resolved.relative_to(parent)
            return resolved
        except ValueError:
            continue
    msg = _(
        "key_path {path} is outside allowed directories (~/.ssh/ or ~/.opk/)"
    ).format(path=resolved)
    raise ConfigError(msg)


def load_config(path: Path | None = None) -> Config:
    """Load and validate the configuration file.

    Args:
        path: Explicit path to the TOML file.  Defaults to
            ``~/.config/opkssh-wrapper/config.toml``.

    Returns:
        A validated :class:`Config` instance.

    Raises:
        ConfigError: On malformed TOML or invalid values.
    """
    config_path = (path or _DEFAULT_CONFIG_PATH).expanduser().resolve()

    if not config_path.is_file():
        return Config()

    try:
        with open(config_path, "rb") as fh:
            data = tomllib.loads(fh.read().decode("utf-8"))
    except Exception as exc:
        msg = _("Failed to parse config file {path}: {error}").format(
            path=config_path,
            error=exc,
        )
        raise ConfigError(msg) from exc

    key_path_raw = data.get("key_path")
    key_path = Path(key_path_raw) if key_path_raw else _DEFAULT_KEY_PATH

    # Validate key_path is within allowed directories.
    _validate_key_path(key_path)

    return Config(
        key_ttl_hours=int(data.get("key_ttl_hours", 24)),
        key_wait_timeout=int(data.get("key_wait_timeout", 10)),
        login_timeout=int(data.get("login_timeout", 120)),
        ssh_path=data.get("ssh_path"),
        opkssh_path=str(data.get("opkssh_path", "opkssh")),
        key_path=key_path,
        aggressive_login=bool(data.get("aggressive_login", False)),
    )
