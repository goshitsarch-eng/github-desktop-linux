"""Loads Kirigami for the QML tests, or a stand-in when it is not installed.

Kirigami is a runtime dependency: users install it from their distribution,
and where it is present the tests import the real module. Plenty of CI images
have Qt but no KF6 though, and skipping every QML test there would mean a
broken binding could land unnoticed. So when the real module is missing we
load ``tests/qmlstub``, which implements just enough of the API for the app's
QML to instantiate.

The stub proves the tree loads, the property names exist and the bindings
evaluate. It does not prove anything about how Kirigami *looks*; the CI job
that runs against real Kirigami is what covers that.
"""

from __future__ import annotations

import os
from pathlib import Path

STUB_PATH = Path(__file__).resolve().parent / "qmlstub"

_registered = False


def real_kirigami_available() -> bool:
    """True when the system has a real org.kde.kirigami QML module."""
    try:
        from PySide6.QtCore import QLibraryInfo
    except Exception:
        return False
    roots = [Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.Qml2ImportsPath))]
    extra = os.environ.get("QML2_IMPORT_PATH") or os.environ.get("QML_IMPORT_PATH")
    if extra:
        roots.extend(Path(part) for part in extra.split(os.pathsep) if part)
    roots.extend(
        Path(part)
        for part in (
            "/usr/lib/qt6/qml",
            "/usr/lib64/qt6/qml",
            "/usr/lib/x86_64-linux-gnu/qt6/qml",
            "/usr/lib/aarch64-linux-gnu/qt6/qml",
        )
    )
    return any((root / "org" / "kde" / "kirigami" / "qmldir").exists() for root in roots)


def _register_stub_attached_types() -> None:
    """Register ``Kirigami.FormData``, which a QML-only stub cannot provide.

    Attached properties need a registered type; the rest of the stub is plain
    QML files under ``qmlstub/org/kde/kirigami``.
    """
    global _registered
    if _registered:
        return
    from PySide6.QtCore import Property, QObject, Signal
    from PySide6.QtQml import QmlAttached, QmlNamedElement

    global QML_IMPORT_NAME, QML_IMPORT_MAJOR_VERSION
    QML_IMPORT_NAME = "org.kde.kirigami"
    QML_IMPORT_MAJOR_VERSION = 1

    class FormDataAttached(QObject):
        changed = Signal()

        def __init__(self, parent: QObject | None = None) -> None:
            super().__init__(parent)
            self._label = ""
            self._is_section = False

        @Property(str, notify=changed)
        def label(self) -> str:
            return self._label

        @label.setter
        def label(self, value: str) -> None:
            self._label = value
            self.changed.emit()

        @Property(bool, notify=changed)
        def isSection(self) -> bool:  # noqa: N802 - QML name
            return self._is_section

        @isSection.setter
        def isSection(self, value: bool) -> None:  # noqa: N802 - QML name
            self._is_section = value
            self.changed.emit()

    @QmlNamedElement("FormData")
    @QmlAttached(FormDataAttached)
    class FormData(QObject):
        def qmlAttachedProperties(self, obj):  # noqa: N802 - Qt API
            return FormDataAttached(obj)

    globals()["_FormData"] = FormData  # keep the type alive
    _registered = True


def prepare_engine(engine) -> str:
    """Point ``engine`` at Kirigami. Returns "real" or "stub"."""
    if real_kirigami_available():
        return "real"
    _register_stub_attached_types()
    engine.addImportPath(str(STUB_PATH))
    return "stub"


# The stub's singletons are compiled per process; a stale disk cache from an
# earlier, different stub would mask edits to it.
os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")
