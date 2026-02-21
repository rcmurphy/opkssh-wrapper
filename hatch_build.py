"""Hatchling build hook: compile gettext .po catalogues to binary .mo files.

This runs automatically during ``python -m build`` (and editable installs)
so that the wheel published to PyPI contains compiled translation catalogues.

Security:
    Only reads files inside the package's own ``locale`` tree.  No user
    input is involved; paths are resolved from the project root constant.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from babel.messages.mofile import write_mo  # type: ignore[import-untyped]
from babel.messages.pofile import read_po  # type: ignore[import-untyped]
from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Compile .po catalogues to .mo before the wheel or sdist is built."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Compile every .po file found under the package locale directory.

        Args:
            version: Build version string (unused).
            build_data: Hatchling build data dict (unused).
        """
        locale_dir = Path(self.root) / "src" / "opkssh_wrapper" / "locale"
        for po_file in sorted(locale_dir.rglob("*.po")):
            mo_file = po_file.with_suffix(".mo")
            _compile_po(po_file, mo_file)
            self.app.display_info(
                f"Compiled {po_file.relative_to(self.root)} → {mo_file.name}"
            )


def _compile_po(po_path: Path, mo_path: Path) -> None:
    """Compile a single .po source file to a binary .mo catalogue.

    Args:
        po_path: Path to the source .po file.
        mo_path: Destination path for the compiled .mo file.
    """
    with po_path.open("rb") as f:
        catalog = read_po(f)
    with mo_path.open("wb") as f:
        write_mo(f, catalog)
