"""Entry-point for the opkssh-wrapper shim.

This module implements the core shim logic:

1. Detect interactive vs non-interactive context.
2. Check for a valid (non-expired) opkssh ephemeral key.
3. If expired, run ``opkssh login`` (interactive) or exit 255 (non-interactive).
4. Wait for the key file to appear on disk.
5. Verify key file permissions.
6. ``exec`` the real ``ssh`` with identity flags prepended.

Security:
    User arguments are **never** modified, interpolated, or shell-expanded.
    The only mutation is prepending ``-o IdentitiesOnly=yes -i <key_path>``
    before the user's original argv.  ``os.execvp`` is used so there is no
    shell in the chain.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from opkssh_wrapper.config import Config, ConfigError, load_config
from opkssh_wrapper.i18n import _
from opkssh_wrapper.ssh import find_real_ssh

_EXPIRY_DIR = Path("~/.local/state/opkssh-wrapper").expanduser()
_EXPIRY_FILE = _EXPIRY_DIR / "key-expiry"

_EXIT_NO_KEY = 255


def _is_interactive() -> bool:
    """Return ``True`` if stderr is attached to a TTY."""
    try:
        return os.isatty(sys.stderr.fileno())
    except (AttributeError, OSError):
        return False


def _read_expiry() -> datetime | None:
    """Read the key-expiry timestamp file.

    Returns:
        The expiry as a timezone-aware UTC datetime, or ``None`` if the
        file is missing or unparseable.
    """
    try:
        text = _EXPIRY_FILE.read_text(encoding="utf-8").strip()
        # Accept both ``Z`` suffix and ``+00:00``.
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except (OSError, ValueError):
        return None


def _write_expiry(ttl_hours: int) -> None:
    """Write a new expiry timestamp (now + *ttl_hours*).

    Creates parent directories with mode ``0o700`` if they don't exist.

    Security:
        The directory is created with restricted permissions so other users
        on a shared system cannot tamper with the expiry file.
    """
    _EXPIRY_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    expiry = datetime.now(tz=timezone.utc) + timedelta(hours=ttl_hours)
    _EXPIRY_FILE.write_text(
        expiry.strftime("%Y-%m-%dT%H:%M:%SZ") + "\n",
        encoding="utf-8",
    )


def _key_is_valid(config: Config) -> bool:
    """Return ``True`` if the ephemeral key exists and has not expired."""
    key = config.key_path.expanduser().resolve()
    if not key.is_file():
        return False
    expiry = _read_expiry()
    if expiry is None:
        return False
    return datetime.now(tz=timezone.utc) < expiry


def _stderr(message: str) -> None:
    """Write a message to stderr."""
    sys.stderr.write(message + "\n")
    sys.stderr.flush()


def _run_opkssh_login(config: Config) -> bool:
    """Execute ``opkssh login`` and return ``True`` on success.

    Security:
        Invoked as a list to avoid shell interpretation.  Stdout is
        discarded (may contain token material); stderr is inherited so
        the user can see authentication prompts.
    """
    cmd = [config.opkssh_path, "login"]
    try:
        # SECURITY: list-form invocation — no shell interpretation.
        result = subprocess.run(  # noqa: S603
            cmd,
            stdin=sys.stdin,
            stdout=subprocess.DEVNULL,
            stderr=sys.stderr,
            timeout=config.login_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _stderr(
            _("opkssh-wrapper: opkssh login timed out after {seconds}s").format(
                seconds=config.login_timeout,
            ),
        )
        return False
    except FileNotFoundError:
        _stderr(
            _("opkssh-wrapper: opkssh binary not found at '{path}'").format(
                path=config.opkssh_path,
            ),
        )
        return False
    return result.returncode == 0


def _wait_for_key(config: Config) -> bool:
    """Poll for the key file to appear on disk.

    Returns ``True`` if the file appeared within the configured timeout.
    """
    key = config.key_path.expanduser().resolve()
    deadline = time.monotonic() + config.key_wait_timeout
    while time.monotonic() < deadline:
        if key.is_file():
            return True
        time.sleep(0.25)
    return False


def _check_key_permissions(config: Config) -> bool:
    """Verify the private key file has mode ``0o600``.

    Returns ``True`` if permissions are correct.

    Security:
        SSH itself rejects keys with overly permissive modes, but we
        provide a clearer error message up-front.
    """
    key = config.key_path.expanduser().resolve()
    mode = key.stat().st_mode & 0o777
    return mode == (stat.S_IRUSR | stat.S_IWUSR)  # 0o600


def _exec_ssh(config: Config, user_args: list[str]) -> None:
    """Replace this process with the real ``ssh``.

    Security:
        ``os.execvp`` is used so there is no intermediate shell.  User
        arguments are passed as a list — never joined into a string.
    """
    real_ssh = find_real_ssh(config.ssh_path)
    key = str(config.key_path.expanduser().resolve())
    # SECURITY: list-form exec preserves argv integrity — no shell interpretation
    final_argv = [
        real_ssh,
        "-o",
        "IdentitiesOnly=yes",
        "-i",
        key,
        *user_args,
    ]
    os.execvp(real_ssh, final_argv)  # noqa: S606


def _print_help() -> None:
    """Display help text to stdout."""
    lines = [
        _("Usage: opkssh-wrapper [ssh arguments ...]"),
        "",
        _(
            "A thin shim that ensures a valid opkssh identity exists "
            "before passing all arguments through to the real ssh binary."
        ),
        "",
        _("Options:"),
        _("  --help     Show this help message and exit"),
        _("  --version  Show version and exit"),
    ]
    sys.stdout.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> None:
    """Shim entry-point.

    Args:
        argv: Command-line arguments.  Defaults to ``sys.argv[1:]``.
    """
    if argv is None:
        argv = sys.argv[1:]

    # Special-case: --help / --version before anything else.
    if "--help" in argv:
        _print_help()
        sys.exit(0)

    if "--version" in argv:
        from opkssh_wrapper import __version__

        sys.stdout.write(f"opkssh-wrapper {__version__}\n")
        sys.exit(0)

    try:
        config = load_config()
    except ConfigError as exc:
        _stderr(
            _("opkssh-wrapper: configuration error: {error}").format(
                error=exc,
            ),
        )
        sys.exit(1)

    interactive = _is_interactive()
    silent = not interactive

    if not _key_is_valid(config):
        if silent and not config.aggressive_login:
            _stderr(
                _(
                    "opkssh-wrapper: key expired, "
                    "run 'opkssh-wrapper login' interactively"
                ),
            )
            sys.exit(_EXIT_NO_KEY)

        if interactive or config.aggressive_login:
            if interactive:
                _stderr(_("Key expired. Authenticating..."))

            if not _run_opkssh_login(config):
                _stderr(_("opkssh-wrapper: opkssh login failed"))
                sys.exit(1)

            _write_expiry(config.key_ttl_hours)

            if not _wait_for_key(config):
                _stderr(
                    _(
                        "opkssh-wrapper: key file did not appear within "
                        "{seconds}s after login"
                    ).format(seconds=config.key_wait_timeout),
                )
                sys.exit(1)

    # At this point the key should exist on disk.
    key_resolved = config.key_path.expanduser().resolve()
    if not key_resolved.is_file():
        _stderr(
            _("opkssh-wrapper: key file {path} does not exist").format(
                path=key_resolved,
            ),
        )
        sys.exit(1)

    if not _check_key_permissions(config):
        actual_mode = key_resolved.stat().st_mode & 0o777
        _stderr(
            _(
                "opkssh-wrapper: key file {path} has mode {mode:#o}, expected 0o600"
            ).format(path=key_resolved, mode=actual_mode),
        )
        sys.exit(1)

    _exec_ssh(config, argv)


if __name__ == "__main__":
    main()
