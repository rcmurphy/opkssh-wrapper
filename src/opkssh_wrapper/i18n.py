"""Internationalization support using gettext.

Provides the ``_()`` function used throughout the package to mark
user-facing strings for translation.
"""

from __future__ import annotations

import gettext
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

_LOCALE_DIR = str(Path(__file__).parent / "locale")

_DOMAIN = "opkssh_wrapper"


def _setup_gettext() -> gettext.GNUTranslations | gettext.NullTranslations:
    """Initialise and return the gettext translation object.

    Respects the ``LANGUAGE``, ``LC_ALL``, ``LC_MESSAGES``, and ``LANG``
    environment variables.  Falls back to ``NullTranslations`` (passthrough)
    when no ``.mo`` file is available for the active locale.
    """
    lang = os.environ.get(
        "LANGUAGE",
        os.environ.get(
            "LC_ALL",
            os.environ.get("LC_MESSAGES", os.environ.get("LANG")),
        ),
    )
    languages: list[str] | None = [lang] if lang else None
    return gettext.translation(
        _DOMAIN,
        localedir=_LOCALE_DIR,
        languages=languages,
        fallback=True,
    )


_translation = _setup_gettext()


def gettext_func(message: str) -> str:
    """Translate *message* via the active locale catalogue."""
    return _translation.gettext(message)


# Export as the conventional ``_`` shorthand.
_: Callable[[str], str] = gettext_func
