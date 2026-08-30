"""Application color scheme (system / light / dark).

The QML side reads :func:`is_dark` through the theme bridge and drives
``Kirigami.Theme`` from it. Everything here stays importable without Qt so the
syntax highlighter, which runs on worker threads, can ask for the current
brightness without touching the GUI.
"""

from __future__ import annotations

import os

from .models import ApplicationTheme

# Cached so syntax highlighting can run off the GUI thread without touching Qt.
_cached_dark = False
_current: str = ApplicationTheme.SYSTEM.value

# Set by the Qt layer to a callable returning True when the desktop's own color
# scheme is dark. Keeping it injectable means this module never imports Qt.
_system_dark_probe = None


def set_system_dark_probe(probe) -> None:
    """Install the callback used to read the desktop's light/dark preference."""
    global _system_dark_probe
    _system_dark_probe = probe


def system_is_dark() -> bool:
    """True when the desktop is currently using a dark color scheme."""
    override = os.environ.get("GITHUB_DESKTOP_FORCE_DARK")
    if override is not None:
        return override == "1"
    probe = _system_dark_probe
    if probe is None:
        return False
    try:
        return bool(probe())
    except Exception:
        return False


def apply_theme(theme: ApplicationTheme | str) -> None:
    """Record the selected theme and refresh the cached brightness."""
    global _cached_dark, _current
    value = theme.value if isinstance(theme, ApplicationTheme) else theme
    _current = value
    if value == ApplicationTheme.DARK.value:
        _cached_dark = True
    elif value == ApplicationTheme.LIGHT.value:
        _cached_dark = False
    else:
        _cached_dark = system_is_dark()


def refresh_system_theme() -> bool:
    """Re-read the desktop preference; returns True when the brightness changed.

    Called by the Qt layer when Plasma broadcasts a color scheme change so the
    app follows the system while the appearance setting is ``System``.
    """
    global _cached_dark
    if _current != ApplicationTheme.SYSTEM.value:
        return False
    dark = system_is_dark()
    if dark == _cached_dark:
        return False
    _cached_dark = dark
    return True


def current_theme() -> str:
    """The configured appearance: ``system``, ``light`` or ``dark``."""
    return _current


def is_dark() -> bool:
    """Thread-safe: never queries Qt. Updated by apply_theme() on the GUI thread."""
    return _cached_dark
