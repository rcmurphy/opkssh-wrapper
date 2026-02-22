"""Locate the real ``ssh`` binary on the system.

The shim may be installed as ``ssh`` on ``$PATH`` (via alias or symlink).
This module ensures we never invoke ourselves recursively.

Security:
    The resolved path is used directly with ``os.execvp``.  We never pass
    it through a shell.  The result is cached for the process lifetime.
"""

from __future__ import annotations

import contextlib
import os
import sys
from functools import lru_cache
from pathlib import Path

from opkssh_wrapper.i18n import _

_FALLBACK_SSH = "/usr/bin/ssh"
_TRUSTED_SSH_DIRS: tuple[str, ...] = ("/usr/bin", "/bin", "/usr/local/bin")


def _own_executables() -> set[str]:
    """Return the set of resolved paths that refer to this process.

    Covers both the Python interpreter (for ``python -m`` invocations)
    and the script entry-point (for Nuitka / console_scripts).
    """
    paths: set[str] = set()
    with contextlib.suppress(AttributeError, OSError):
        paths.add(os.path.realpath(sys.executable))
    with contextlib.suppress(IndexError, OSError):
        paths.add(os.path.realpath(sys.argv[0]))
    return paths


@lru_cache(maxsize=1)
def find_real_ssh(ssh_path_override: str | None = None) -> str:
    """Locate the real ``ssh`` binary, skipping the shim itself.

    Args:
        ssh_path_override: Explicit path from configuration.  If set and
            valid, it is returned immediately.

    Returns:
        Absolute path to the real ``ssh`` binary.

    Raises:
        FileNotFoundError: If no usable ``ssh`` binary can be found.

    Security:
        Iterates ``$PATH`` and resolves symlinks to avoid invoking the
        shim recursively.
    """
    if ssh_path_override:
        candidate = Path(ssh_path_override).resolve()
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            return str(candidate)
        msg = _("Configured ssh_path {path} is not an executable file").format(
            path=ssh_path_override,
        )
        raise FileNotFoundError(msg)

    own = _own_executables()

    for directory in _TRUSTED_SSH_DIRS:
        candidate_path = os.path.join(directory, "ssh")
        try:
            resolved = os.path.realpath(candidate_path)
        except OSError:
            continue
        if resolved in own:
            continue
        if os.path.isfile(resolved) and os.access(resolved, os.X_OK):
            return resolved

    # Last-resort fallback.
    if os.path.isfile(_FALLBACK_SSH) and os.access(_FALLBACK_SSH, os.X_OK):
        return _FALLBACK_SSH

    msg = _(
        "Could not find a real ssh binary in trusted directories or at {fallback}"
    ).format(
        fallback=_FALLBACK_SSH,
    )
    raise FileNotFoundError(msg)
