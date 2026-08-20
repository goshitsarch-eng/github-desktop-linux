"""Adwaita color scheme (system / light / dark)."""

from __future__ import annotations

from .models import ApplicationTheme


def apply_theme(theme: ApplicationTheme | str) -> None:
    value = theme.value if isinstance(theme, ApplicationTheme) else theme
    try:
        import gi

        gi.require_version("Adw", "1")
        from gi.repository import Adw

        manager = Adw.StyleManager.get_default()
        mapping = {
            ApplicationTheme.LIGHT.value: Adw.ColorScheme.FORCE_LIGHT,
            ApplicationTheme.DARK.value: Adw.ColorScheme.FORCE_DARK,
            ApplicationTheme.SYSTEM.value: Adw.ColorScheme.DEFAULT,
        }
        manager.set_color_scheme(mapping.get(value, Adw.ColorScheme.DEFAULT))
    except Exception:
        pass


def is_dark() -> bool:
    try:
        import gi

        gi.require_version("Adw", "1")
        from gi.repository import Adw

        return bool(Adw.StyleManager.get_default().get_dark())
    except Exception:
        return False
