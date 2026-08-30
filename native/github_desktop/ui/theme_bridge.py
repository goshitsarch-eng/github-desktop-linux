"""Light / dark / system appearance for the Qt UI.

Kirigami takes its palette from the platform theme, which on Plasma is the
user's own color scheme. "System" therefore means *do nothing* and let Breeze
decide; "Light" and "Dark" override the QML color set for this application
only, exactly like Desktop's appearance preference.

Following the system is implemented against ``QStyleHints.colorScheme``, the
Qt 6.5+ API that Plasma, GNOME and the freedesktop appearance portal all feed.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QGuiApplication, Qt

from .. import theme as theme_state
from ..models import ApplicationTheme


def system_is_dark() -> bool:
    """True when the desktop's own color scheme is dark."""
    app = QGuiApplication.instance()
    if app is None:
        return False
    hints = app.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is not None:
        try:
            return scheme() == Qt.ColorScheme.Dark
        except Exception:
            pass
    # Older Qt: compare window text against window background.
    palette = app.palette()
    background = palette.window().color()
    text = palette.windowText().color()
    return text.lightness() > background.lightness()


class ThemeBridge(QObject):
    """Exposes the resolved appearance to QML and follows the desktop."""

    changed = Signal()

    def __init__(self, store, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store
        theme_state.set_system_dark_probe(system_is_dark)
        theme_state.apply_theme(store.settings.theme)
        app = QGuiApplication.instance()
        if app is not None:
            hints = app.styleHints()
            signal = getattr(hints, "colorSchemeChanged", None)
            if signal is not None:
                signal.connect(self._on_system_scheme_changed)

    def _on_system_scheme_changed(self, *_args: object) -> None:
        if theme_state.refresh_system_theme():
            self.changed.emit()

    @Property(bool, notify=changed)
    def isDark(self) -> bool:  # noqa: N802 - QML style
        return theme_state.is_dark()

    @Property(str, notify=changed)
    def current(self) -> str:
        return theme_state.current_theme()

    @Property(bool, notify=changed)
    def followsSystem(self) -> bool:  # noqa: N802 - QML style
        return theme_state.current_theme() == ApplicationTheme.SYSTEM.value

    @Slot(str)
    def setTheme(self, value: str) -> None:  # noqa: N802 - QML style
        """Persist and apply an appearance choice from Preferences."""
        self._store.set_theme(value)
        theme_state.apply_theme(value)
        self.changed.emit()

    @Slot()
    def refresh(self) -> None:
        theme_state.apply_theme(self._store.settings.theme)
        self.changed.emit()
