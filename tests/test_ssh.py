"""Tests for opkssh_wrapper.ssh — finding the real ssh binary."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from opkssh_wrapper.ssh import _own_executables, find_real_ssh

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _clear_ssh_cache() -> None:  # type: ignore[misc]
    """Clear the lru_cache on find_real_ssh before each test."""
    find_real_ssh.cache_clear()


class TestFindRealSsh:
    """Locating the real ssh binary."""

    def test_explicit_override(self, tmp_path: Path) -> None:
        fake_ssh = tmp_path / "ssh"
        fake_ssh.write_text("#!/bin/sh\n", encoding="utf-8")
        fake_ssh.chmod(0o755)
        result = find_real_ssh(str(fake_ssh))
        assert result == str(fake_ssh.resolve())

    def test_explicit_override_missing_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match="not an executable"):
            find_real_ssh("/nonexistent/ssh")

    def test_skips_self_on_path(self, tmp_path: Path) -> None:
        """Shim is first on PATH but find_real_ssh skips it."""
        # Create a "shim" that resolves to our own executable.
        shim_dir = tmp_path / "shim_bin"
        shim_dir.mkdir()
        shim_ssh = shim_dir / "ssh"
        # Symlink to this process's executable to simulate the shim.
        own = os.path.realpath(sys.argv[0])
        shim_ssh.symlink_to(own)

        # Create a "real" ssh binary.
        real_dir = tmp_path / "real_bin"
        real_dir.mkdir()
        real_ssh = real_dir / "ssh"
        real_ssh.write_text("#!/bin/sh\n", encoding="utf-8")
        real_ssh.chmod(0o755)

        test_path = f"{shim_dir}{os.pathsep}{real_dir}"
        with mock.patch.dict(os.environ, {"PATH": test_path}):
            result = find_real_ssh(None)

        assert result == str(real_ssh.resolve())

    def test_fallback_to_usr_bin_ssh(self, tmp_path: Path) -> None:
        """When PATH has nothing, fall back to /usr/bin/ssh."""
        with mock.patch.dict(os.environ, {"PATH": str(tmp_path)}):
            if os.path.isfile("/usr/bin/ssh"):
                result = find_real_ssh(None)
                assert result == "/usr/bin/ssh"
            else:
                with pytest.raises(FileNotFoundError, match="Could not find"):
                    find_real_ssh(None)

    def test_no_ssh_anywhere_raises(self, tmp_path: Path) -> None:
        with (
            mock.patch.dict(os.environ, {"PATH": str(tmp_path)}),
            mock.patch(
                "opkssh_wrapper.ssh._FALLBACK_SSH",
                str(tmp_path / "nope"),
            ),
            pytest.raises(FileNotFoundError, match="Could not find"),
        ):
            find_real_ssh(None)


class TestOwnExecutables:
    """_own_executables returns paths that refer to this process."""

    def test_returns_set(self) -> None:
        result = _own_executables()
        assert isinstance(result, set)
        assert len(result) >= 1
