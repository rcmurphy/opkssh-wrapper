"""Hatch build hook: compile gettext .po catalogues to binary .mo files.

This hook runs at build time (when executing ``python -m build``) and
compiles every ``*.po`` file found under ``src/opkssh_wrapper/locale`` into
its corresponding ``*.mo`` binary catalogue.  The compiled catalogues are
then included in the distribution so that gettext can find them at runtime.
"""

from __future__ import annotations

import pathlib
import warnings
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


# BuildHookInterface is a generic class whose type parameter is only used
# internally by hatchling; there is no public API to specify it.
class CustomBuildHook(BuildHookInterface):  # type: ignore[type-arg]
    """Compile gettext .po files to .mo files before building the distribution."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Compile all .po catalogues to .mo before the build.

        Args:
            version: The version of the package being built (unused).
            build_data: Mutable build metadata provided by hatchling (unused).

        Security:
            Only processes files within the known locale directory tree.
            File paths are constructed internally and never derived from
            external input.
        """
        # Imported here rather than at module level so that babel is only
        # required when the build hook actually executes (i.e. during
        # ``python -m build``), not when the module is merely imported.
        from babel.messages.mofile import write_mo  # type: ignore[import-untyped]
        from babel.messages.pofile import read_po  # type: ignore[import-untyped]

        locale_root = pathlib.Path(self.root) / "src" / "opkssh_wrapper" / "locale"
        po_files = sorted(locale_root.glob("*/LC_MESSAGES/*.po"))
        if not po_files:
            warnings.warn(
                f"No .po files found under {locale_root}; "
                "no .mo catalogues will be compiled.",
                stacklevel=1,
            )
            return
        for po_file in po_files:
            mo_file = po_file.with_suffix(".mo")
            with po_file.open("rb") as f_in:
                catalog = read_po(f_in)
            with mo_file.open("wb") as f_out:
                write_mo(f_out, catalog)
            self.app.display_info(
                f"Compiled {po_file.relative_to(self.root)} → {mo_file.name}"
            )
