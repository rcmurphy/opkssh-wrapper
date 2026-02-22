"""Tests for opkssh_wrapper.main — the core shim logic."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from opkssh_wrapper.config import Config
from opkssh_wrapper.main import (
    _check_key_permissions,
    _is_interactive,
    _key_is_valid,
    _read_expiry,
    _wait_for_key,
    _write_expiry,
    main,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_key(path: Path, mode: int = 0o600) -> Path:
    """Create a fake key file with the given permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fake-key-content\n", encoding="utf-8")
    path.chmod(mode)
    return path


def _write_expiry_file(expiry_file: Path, dt: datetime) -> None:
    """Write an ISO-8601 timestamp to the given path."""
    expiry_file.parent.mkdir(parents=True, exist_ok=True)
    expiry_file.write_text(
        dt.strftime("%Y-%m-%dT%H:%M:%SZ") + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# _is_interactive
# ---------------------------------------------------------------------------


class TestIsInteractive:
    """Detect whether stderr is a TTY."""

    def test_non_tty(self) -> None:
        # In test environments stderr is usually not a TTY.
        result = _is_interactive()
        assert isinstance(result, bool)

    def test_oserror_returns_false(self) -> None:
        with mock.patch("sys.stderr") as mock_stderr:
            mock_stderr.fileno.side_effect = OSError("not a tty")
            assert _is_interactive() is False


# ---------------------------------------------------------------------------
# _read_expiry / _write_expiry
# ---------------------------------------------------------------------------


class TestExpiry:
    """Read and write the key-expiry timestamp file."""

    def test_write_then_read(self, tmp_path: Path) -> None:
        expiry_file = tmp_path / "state" / "key-expiry"
        with (
            mock.patch("opkssh_wrapper.main._EXPIRY_DIR", tmp_path / "state"),
            mock.patch("opkssh_wrapper.main._EXPIRY_FILE", expiry_file),
        ):
            _write_expiry(24)
            result = _read_expiry()
        assert result is not None
        assert result > datetime.now(tz=timezone.utc)

    def test_read_missing_returns_none(self, tmp_path: Path) -> None:
        with mock.patch(
            "opkssh_wrapper.main._EXPIRY_FILE",
            tmp_path / "nonexistent",
        ):
            assert _read_expiry() is None

    def test_read_corrupt_returns_none(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "key-expiry"
        bad_file.write_text("not-a-date\n", encoding="utf-8")
        with mock.patch("opkssh_wrapper.main._EXPIRY_FILE", bad_file):
            assert _read_expiry() is None

    def test_read_iso_z_suffix(self, tmp_path: Path) -> None:
        f = tmp_path / "key-expiry"
        f.write_text("2099-01-01T00:00:00Z\n", encoding="utf-8")
        with mock.patch("opkssh_wrapper.main._EXPIRY_FILE", f):
            result = _read_expiry()
        assert result is not None
        assert result.year == 2099


# ---------------------------------------------------------------------------
# _key_is_valid
# ---------------------------------------------------------------------------


class TestKeyIsValid:
    """Determine whether the ephemeral key is still valid."""

    def test_valid_key(self, tmp_path: Path) -> None:
        ssh_dir = tmp_path / ".ssh"
        key = _make_key(ssh_dir / "id_ecdsa")
        config = Config(key_path=key)
        future = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        expiry_file = tmp_path / "state" / "key-expiry"
        _write_expiry_file(expiry_file, future)
        with mock.patch("opkssh_wrapper.main._EXPIRY_FILE", expiry_file):
            assert _key_is_valid(config) is True

    def test_expired_key(self, tmp_path: Path) -> None:
        ssh_dir = tmp_path / ".ssh"
        key = _make_key(ssh_dir / "id_ecdsa")
        config = Config(key_path=key)
        past = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        expiry_file = tmp_path / "state" / "key-expiry"
        _write_expiry_file(expiry_file, past)
        with mock.patch("opkssh_wrapper.main._EXPIRY_FILE", expiry_file):
            assert _key_is_valid(config) is False

    def test_missing_key_file(self, tmp_path: Path) -> None:
        config = Config(key_path=tmp_path / ".ssh" / "id_ecdsa")
        assert _key_is_valid(config) is False

    def test_missing_expiry_file(self, tmp_path: Path) -> None:
        ssh_dir = tmp_path / ".ssh"
        key = _make_key(ssh_dir / "id_ecdsa")
        config = Config(key_path=key)
        with mock.patch(
            "opkssh_wrapper.main._EXPIRY_FILE",
            tmp_path / "nonexistent",
        ):
            assert _key_is_valid(config) is False


# ---------------------------------------------------------------------------
# _check_key_permissions
# ---------------------------------------------------------------------------


class TestCheckKeyPermissions:
    """Key file must be 0o600."""

    def test_correct_permissions(self, tmp_path: Path) -> None:
        key = _make_key(tmp_path / "id_ecdsa", mode=0o600)
        config = Config(key_path=key)
        assert _check_key_permissions(config) is True

    def test_wrong_permissions(self, tmp_path: Path) -> None:
        key = _make_key(tmp_path / "id_ecdsa", mode=0o644)
        config = Config(key_path=key)
        assert _check_key_permissions(config) is False


# ---------------------------------------------------------------------------
# _wait_for_key
# ---------------------------------------------------------------------------


class TestWaitForKey:
    """Poll for key file to appear on disk."""

    def test_key_already_exists(self, tmp_path: Path) -> None:
        key = _make_key(tmp_path / "id_ecdsa")
        config = Config(key_path=key, key_wait_timeout=1)
        assert _wait_for_key(config) is True

    def test_key_appears_after_delay(self, tmp_path: Path) -> None:
        key_path = tmp_path / "id_ecdsa"
        config = Config(key_path=key_path, key_wait_timeout=5)

        import threading

        def create_key() -> None:
            time.sleep(0.5)
            _make_key(key_path)

        t = threading.Thread(target=create_key)
        t.start()
        assert _wait_for_key(config) is True
        t.join()

    def test_key_never_appears(self, tmp_path: Path) -> None:
        config = Config(key_path=tmp_path / "nope", key_wait_timeout=1)
        assert _wait_for_key(config) is False


# ---------------------------------------------------------------------------
# main() — integration-level tests
# ---------------------------------------------------------------------------


class TestMainHelp:
    """--help and --version flags."""

    def test_help_exits_zero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_version_exits_zero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0


class TestMainNonInteractiveExpired:
    """Non-interactive + expired key → exit 255."""

    def test_exits_255_silent(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        key = ssh_dir / "id_ecdsa"
        # Don't create the key file — it's expired/missing.
        config = Config(key_path=key, aggressive_login=False)

        monkeypatch.setattr("opkssh_wrapper.main._is_interactive", lambda: False)
        monkeypatch.setattr("opkssh_wrapper.main.load_config", lambda: config)
        monkeypatch.setattr(
            "opkssh_wrapper.main._key_is_valid",
            lambda c: False,
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["user@host"])
        assert exc_info.value.code == 255


class TestMainNonInteractiveAggressive:
    """Non-interactive + aggressive_login → attempts login."""

    def test_aggressive_attempts_login(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        key = ssh_dir / "id_ecdsa"
        config = Config(
            key_path=key,
            aggressive_login=True,
            key_wait_timeout=1,
        )

        monkeypatch.setattr("opkssh_wrapper.main._is_interactive", lambda: False)
        monkeypatch.setattr("opkssh_wrapper.main.load_config", lambda: config)
        monkeypatch.setattr(
            "opkssh_wrapper.main._key_is_valid",
            lambda c: False,
        )
        # Login fails.
        monkeypatch.setattr(
            "opkssh_wrapper.main._run_opkssh_login",
            lambda c: False,
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["user@host"])
        assert exc_info.value.code == 1


class TestMainLoginFailure:
    """opkssh login failure → shim exits nonzero, ssh never called."""

    def test_login_failure_no_ssh(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        key = ssh_dir / "id_ecdsa"
        config = Config(key_path=key)

        monkeypatch.setattr("opkssh_wrapper.main._is_interactive", lambda: True)
        monkeypatch.setattr("opkssh_wrapper.main.load_config", lambda: config)
        monkeypatch.setattr(
            "opkssh_wrapper.main._key_is_valid",
            lambda c: False,
        )
        monkeypatch.setattr(
            "opkssh_wrapper.main._run_opkssh_login",
            lambda c: False,
        )
        exec_called = False

        def mock_exec(c: Config, args: list[str]) -> None:
            nonlocal exec_called
            exec_called = True

        monkeypatch.setattr("opkssh_wrapper.main._exec_ssh", mock_exec)

        with pytest.raises(SystemExit) as exc_info:
            main(["user@host"])
        assert exc_info.value.code == 1
        assert exec_called is False


class TestMainKeyWaitTimeout:
    """Key file never appears → shim exits nonzero."""

    def test_key_wait_timeout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        key = ssh_dir / "id_ecdsa"
        config = Config(key_path=key, key_wait_timeout=1)

        monkeypatch.setattr("opkssh_wrapper.main._is_interactive", lambda: True)
        monkeypatch.setattr("opkssh_wrapper.main.load_config", lambda: config)
        monkeypatch.setattr(
            "opkssh_wrapper.main._key_is_valid",
            lambda c: False,
        )
        monkeypatch.setattr(
            "opkssh_wrapper.main._run_opkssh_login",
            lambda c: True,
        )
        # Key file never gets created → _wait_for_key returns False.

        with pytest.raises(SystemExit) as exc_info:
            main(["user@host"])
        assert exc_info.value.code == 1


class TestMainPermissionCheck:
    """Key with bad permissions → shim refuses."""

    def test_bad_permissions_exits(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ssh_dir = tmp_path / ".ssh"
        key = _make_key(ssh_dir / "id_ecdsa", mode=0o644)
        config = Config(key_path=key)

        monkeypatch.setattr("opkssh_wrapper.main._is_interactive", lambda: True)
        monkeypatch.setattr("opkssh_wrapper.main.load_config", lambda: config)
        monkeypatch.setattr(
            "opkssh_wrapper.main._key_is_valid",
            lambda c: True,
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["user@host"])
        assert exc_info.value.code == 1


class TestMainSuccessfulExec:
    """Happy path: valid key → exec ssh with identity flags."""

    def test_exec_called_with_correct_args(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ssh_dir = tmp_path / ".ssh"
        key = _make_key(ssh_dir / "id_ecdsa", mode=0o600)
        config = Config(key_path=key)

        monkeypatch.setattr("opkssh_wrapper.main._is_interactive", lambda: True)
        monkeypatch.setattr("opkssh_wrapper.main.load_config", lambda: config)
        monkeypatch.setattr(
            "opkssh_wrapper.main._key_is_valid",
            lambda c: True,
        )

        captured_args: list[str] = []

        def mock_exec(c: Config, args: list[str]) -> None:
            captured_args.extend(args)

        monkeypatch.setattr("opkssh_wrapper.main._exec_ssh", mock_exec)

        main(["user@host", "-p", "2222"])
        assert captured_args == ["user@host", "-p", "2222"]


class TestMainLoginThenExec:
    """Expired key → login succeeds → key appears → exec ssh."""

    def test_login_success_flow(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir(parents=True)
        key_path = ssh_dir / "id_ecdsa"
        config = Config(key_path=key_path, key_wait_timeout=2)

        monkeypatch.setattr("opkssh_wrapper.main._is_interactive", lambda: True)
        monkeypatch.setattr("opkssh_wrapper.main.load_config", lambda: config)
        monkeypatch.setattr(
            "opkssh_wrapper.main._key_is_valid",
            lambda c: False,
        )

        expiry_dir = tmp_path / "state"
        expiry_file = expiry_dir / "key-expiry"
        monkeypatch.setattr("opkssh_wrapper.main._EXPIRY_DIR", expiry_dir)
        monkeypatch.setattr("opkssh_wrapper.main._EXPIRY_FILE", expiry_file)

        def mock_login(c: Config) -> bool:
            # Simulate opkssh writing the key.
            _make_key(key_path, mode=0o600)
            return True

        monkeypatch.setattr("opkssh_wrapper.main._run_opkssh_login", mock_login)

        captured_args: list[str] = []

        def mock_exec(c: Config, args: list[str]) -> None:
            captured_args.extend(args)

        monkeypatch.setattr("opkssh_wrapper.main._exec_ssh", mock_exec)

        main(["-v", "user@host"])
        assert captured_args == ["-v", "user@host"]


# ---------------------------------------------------------------------------
# Argument passthrough — Hypothesis fuzz
# ---------------------------------------------------------------------------


class TestArgumentPassthrough:
    """User arguments must reach ssh completely unmodified."""

    @given(
        args=st.lists(
            st.text(
                alphabet=st.characters(
                    blacklist_categories=("Cs",),
                    blacklist_characters=("\x00",),
                ),
                min_size=1,
                max_size=50,
            ),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=200)
    def test_user_args_are_never_modified(
        self,
        args: list[str],
    ) -> None:
        """The shim must not alter, reorder, or drop user arguments."""
        import tempfile
        from pathlib import Path

        # Skip if args contain --help or --version (they trigger early exit).
        if "--help" in args or "--version" in args:
            return

        tmpdir = Path(tempfile.mkdtemp())
        ssh_dir = tmpdir / ".ssh"
        key = _make_key(ssh_dir / "id_ecdsa", mode=0o600)
        config = Config(key_path=key)

        captured_args: list[str] = []

        def mock_exec(c: Config, user_args: list[str]) -> None:
            captured_args.extend(user_args)

        with (
            mock.patch(
                "opkssh_wrapper.main._is_interactive",
                return_value=True,
            ),
            mock.patch(
                "opkssh_wrapper.main.load_config",
                return_value=config,
            ),
            mock.patch(
                "opkssh_wrapper.main._key_is_valid",
                return_value=True,
            ),
            mock.patch(
                "opkssh_wrapper.main._exec_ssh",
                side_effect=mock_exec,
            ),
        ):
            main(args)

        assert captured_args == args


# ---------------------------------------------------------------------------
# Config error handling in main
# ---------------------------------------------------------------------------


class TestMainConfigError:
    """Malformed config → exit 1."""

    def test_config_error_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from opkssh_wrapper.config import ConfigError

        monkeypatch.setattr(
            "opkssh_wrapper.main.load_config",
            mock.Mock(side_effect=ConfigError("bad config")),
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["user@host"])
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# _run_opkssh_login edge cases
# ---------------------------------------------------------------------------


class TestRunOpksshLogin:
    """Edge cases for _run_opkssh_login."""

    def test_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Login times out → returns False."""
        import subprocess as sp

        from opkssh_wrapper.main import _run_opkssh_login

        config = Config(login_timeout=1)
        monkeypatch.setattr(
            "opkssh_wrapper.main.subprocess.run",
            mock.Mock(side_effect=sp.TimeoutExpired(cmd=["opkssh"], timeout=1)),
        )
        assert _run_opkssh_login(config) is False

    def test_binary_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """opkssh binary missing → returns False."""
        from opkssh_wrapper.main import _run_opkssh_login

        config = Config(opkssh_path="/nonexistent/opkssh")
        monkeypatch.setattr(
            "opkssh_wrapper.main.subprocess.run",
            mock.Mock(side_effect=FileNotFoundError()),
        )
        assert _run_opkssh_login(config) is False

    def test_login_returns_nonzero(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """opkssh login returns nonzero → returns False."""
        from opkssh_wrapper.main import _run_opkssh_login

        config = Config()
        mock_result = mock.Mock()
        mock_result.returncode = 1
        monkeypatch.setattr(
            "opkssh_wrapper.main.subprocess.run",
            mock.Mock(return_value=mock_result),
        )
        assert _run_opkssh_login(config) is False

    def test_login_returns_zero(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """opkssh login returns zero → returns True."""
        from opkssh_wrapper.main import _run_opkssh_login

        config = Config()
        mock_result = mock.Mock()
        mock_result.returncode = 0
        monkeypatch.setattr(
            "opkssh_wrapper.main.subprocess.run",
            mock.Mock(return_value=mock_result),
        )
        assert _run_opkssh_login(config) is True


# ---------------------------------------------------------------------------
# _exec_ssh
# ---------------------------------------------------------------------------


class TestExecSsh:
    """Test _exec_ssh constructs correct argv."""

    def test_exec_constructs_correct_argv(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from opkssh_wrapper.main import _exec_ssh

        ssh_dir = tmp_path / ".ssh"
        key = _make_key(ssh_dir / "id_ecdsa")

        captured: list[object] = []

        def mock_execvp(path: str, argv: list[str]) -> None:
            captured.append((path, argv))

        monkeypatch.setattr("os.execvp", mock_execvp)
        from opkssh_wrapper.ssh import find_real_ssh

        find_real_ssh.cache_clear()
        fake_ssh = tmp_path / "ssh"
        fake_ssh.write_text("#!/bin/sh\n", encoding="utf-8")
        fake_ssh.chmod(0o755)
        config_with_ssh = Config(
            key_path=key,
            ssh_path=str(fake_ssh),
        )
        _exec_ssh(config_with_ssh, ["-v", "user@host"])

        assert len(captured) == 1
        _path, argv = captured[0]  # type: ignore[misc]
        assert "-o" in argv
        assert "IdentitiesOnly=yes" in argv
        assert "-i" in argv
        assert "-v" in argv
        assert "user@host" in argv


# ---------------------------------------------------------------------------
# Key missing after validation
# ---------------------------------------------------------------------------


class TestMainKeyMissingAfterValidation:
    """Key file passes validity but doesn't exist on disk."""

    def test_key_missing_after_valid(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        key = ssh_dir / "id_ecdsa"
        # Don't actually create the key file.
        config = Config(key_path=key)

        monkeypatch.setattr(
            "opkssh_wrapper.main._is_interactive",
            lambda: True,
        )
        monkeypatch.setattr(
            "opkssh_wrapper.main.load_config",
            lambda: config,
        )
        # _key_is_valid returns True but the file doesn't exist.
        monkeypatch.setattr(
            "opkssh_wrapper.main._key_is_valid",
            lambda c: True,
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["user@host"])
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# _stderr helper
# ---------------------------------------------------------------------------


class TestStderr:
    """Test the _stderr helper writes to stderr."""

    def test_stderr_writes(self) -> None:
        from opkssh_wrapper.main import _stderr

        with mock.patch("sys.stderr") as mock_err:
            _stderr("test message")
            mock_err.write.assert_called_once_with("test message\n")
            mock_err.flush.assert_called_once()
