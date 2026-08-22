"""Adwaita color scheme (system / light / dark)."""

from __future__ import annotations

from .models import ApplicationTheme

# Cached so syntax highlighting can run off the GTK thread without touching Adw.
_cached_dark = False


def apply_theme(theme: ApplicationTheme | str) -> None:
    global _cached_dark
    value = theme.value if isinstance(theme, ApplicationTheme) else theme
    if value == ApplicationTheme.DARK.value:
        _cached_dark = True
    elif value == ApplicationTheme.LIGHT.value:
        _cached_dark = False
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
        _cached_dark = bool(manager.get_dark())
    except Exception:
        pass


def is_dark() -> bool:
    """Thread-safe: never queries Adw. Updated by apply_theme() on the GTK thread."""
    return _cached_dark
