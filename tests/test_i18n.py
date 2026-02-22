"""Tests for opkssh_wrapper.i18n — internationalisation support."""

from __future__ import annotations

from opkssh_wrapper.i18n import _, gettext_func


class TestI18n:
    """Basic i18n sanity checks."""

    def test_passthrough_english(self) -> None:
        result = _("Key expired. Authenticating...")
        assert result == "Key expired. Authenticating..."

    def test_gettext_func_is_callable(self) -> None:
        assert callable(gettext_func)

    def test_gettext_func_returns_string(self) -> None:
        result = gettext_func("hello")
        assert isinstance(result, str)

    def test_underscore_is_gettext_func(self) -> None:
        # _ should be the same function as gettext_func.
        assert _("test") == gettext_func("test")
