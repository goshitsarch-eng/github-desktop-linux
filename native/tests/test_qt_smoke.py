"""Qt 6 / Kirigami smoke tests: the QML tree loads and the bridge answers it.

These run headless (``QT_QPA_PLATFORM=offscreen``). Where the system has
Kirigami they exercise the real module; otherwise ``tests/kirigami_stub``
supplies a stand-in so a broken binding still fails here. See that module for
what the stub does and does not prove.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")

pytest.importorskip("PySide6")

from tests.kirigami_stub import prepare_engine, real_kirigami_available  # noqa: E402

QML_DIR = Path(__file__).resolve().parents[1] / "github_desktop" / "ui" / "qml"


@pytest.fixture(scope="module")
def qt_app():
    """One QApplication per process; Qt does not allow a second."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def bridge(qt_app, isolated_config, git_repo):
    from github_desktop.git.ops import get_status
    from github_desktop.store import AppStore
    from github_desktop.ui.bridge import AppBridge

    store = AppStore()
    # Past the first-run flow: these tests are about the repository workspace.
    store.finish_welcome()
    repos = store.add_repositories([str(git_repo)])
    (git_repo / "README.md").write_text("hello\nchanged\n", encoding="utf-8")
    store.state_for(repos[0]).status = get_status(str(git_repo))
    store.select_repository(repos[0].id)
    return AppBridge(store)


def _load_main_window(qt_app, bridge, *, capture_messages: list[str] | None = None):
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine

    from github_desktop.ui.popups import PopupBridge
    from github_desktop.ui.theme_bridge import ThemeBridge

    engine = QQmlApplicationEngine()
    flavour = prepare_engine(engine)
    theming = ThemeBridge(bridge.store)
    popups = PopupBridge(bridge.store, bridge)
    context = engine.rootContext()
    context.setContextProperty("app", bridge)
    context.setContextProperty("theming", theming)
    context.setContextProperty("popups", popups)
    engine.addImportPath(str(QML_DIR))
    warnings: list[str] = []
    engine.warnings.connect(lambda errors: warnings.extend(str(e.toString()) for e in errors))
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    # Hold references: the engine does not own the bridges.
    engine._keepalive = (bridge, theming, popups)
    if capture_messages is not None:
        warnings.extend(capture_messages)
    return engine, warnings, flavour


@pytest.fixture
def qt_messages():
    """Collect everything Qt logs while the QML tree is built.

    A ``ReferenceError`` in a binding or a signal that shadows a base-class one
    does not stop the window loading -- it just quietly breaks that one thing at
    runtime. Qt reports both through the message handler, so the smoke test
    watches it rather than only checking that a root object exists.
    """
    from PySide6.QtCore import qInstallMessageHandler

    messages: list[str] = []

    def handler(mode, context, message):
        messages.append(str(message))

    previous = qInstallMessageHandler(handler)
    try:
        yield messages
    finally:
        qInstallMessageHandler(previous)


#: Qt log lines that mean the QML is wrong, not merely unusual.
BROKEN_QML = (
    "is not a type",
    "Cannot assign",
    "ReferenceError",
    "TypeError",
    "Unable to assign",
    "Duplicate signal name",
    "overrides a member of the base object",
    "Binding loop",
    "is not available",
    "Cannot read property",
)


def test_main_window_loads(qt_app, bridge, qt_messages) -> None:
    engine, warnings, flavour = _load_main_window(qt_app, bridge, capture_messages=qt_messages)
    assert engine.rootObjects(), f"Main.qml did not load ({flavour}): {warnings}"
    broken = [w for w in warnings if any(marker in w for marker in BROKEN_QML)]
    assert not broken, "\n".join(broken)


def test_every_dialog_component_loads(qt_app, bridge, qt_messages) -> None:
    """Each PopupType maps to a QML dialog that compiles and instantiates.

    Compiling only proves the syntax; creating the object is what evaluates the
    bindings, which is where a typo in a bridge property shows up.
    """
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent, QQmlApplicationEngine

    from github_desktop.models import PopupType
    from github_desktop.ui.popups import DIALOG_FOR_POPUP, PopupBridge
    from github_desktop.ui.theme_bridge import ThemeBridge

    engine = QQmlApplicationEngine()
    prepare_engine(engine)
    engine.addImportPath(str(QML_DIR))
    context = engine.rootContext()
    theming = ThemeBridge(bridge.store)
    popups = PopupBridge(bridge.store, bridge)
    context.setContextProperty("app", bridge)
    context.setContextProperty("theming", theming)
    context.setContextProperty("popups", popups)

    failures = []
    created = {}
    for popup_type, name in sorted(DIALOG_FOR_POPUP.items()):
        path = QML_DIR / "dialogs" / f"{name}.qml"
        assert path.exists(), f"{name}.qml is referenced but missing"
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
        if component.isError():
            failures.append((name, component.errorString()))
            continue
        dialog = component.create()
        if dialog is None:
            failures.append((name, component.errorString()))
            continue
        # Parent to the engine so it tears the dialogs down before the root
        # context goes; otherwise bindings re-evaluate against a dead context.
        dialog.setParent(engine)
        # Every dialog reads its popup type and payload; give it real ones.
        dialog.setProperty("popupKind", popup_type)
        dialog.setProperty("payload", {"branch": "main", "name": "demo", "sha": "abc1234"})
        created[name] = dialog
    assert not failures, failures
    assert set(DIALOG_FOR_POPUP) == {p.value for p in PopupType}

    broken = [m for m in qt_messages if any(marker in m for marker in BROKEN_QML)]
    assert not broken, "\n".join(broken)
    assert len(created) == len(set(DIALOG_FOR_POPUP.values()))


def test_bridge_exposes_view_state(bridge) -> None:
    """The properties QML binds to answer without a window."""
    assert bridge.viewMode == "repository"
    assert bridge.repositoryState == "ready"
    assert bridge.appName in bridge.windowTitle
    assert bridge.section in {"changes", "history"}
    assert bridge.changedFileCount >= 1
    assert bridge.repositories.count >= 1
    assert bridge.changedFiles.count >= 1

    row = bridge.changedFiles.get(0)
    assert row["path"] == "README.md"
    assert row["statusLetter"] == "M"
    assert row["statusColor"] == "neutral"

    push = bridge.pushPull
    assert push["label"]
    assert "icon" in push and "action" in push

    form = bridge.commitForm
    assert form["visible"] is True
    assert form["buttonLabel"].startswith("Commit to")


def test_bridge_commit_message_round_trip(bridge) -> None:
    bridge.setCommitMessage("Summary", "Body")
    assert bridge.commitForm["summary"] == "Summary"
    assert bridge.commitForm["description"] == "Body"
    assert bridge.commitForm["canCommit"] is True


def test_bridge_section_switch(bridge) -> None:
    bridge.setSection("history")
    assert bridge.section == "history"
    bridge.setSection("changes")
    assert bridge.section == "changes"


def test_diff_rows_carry_markup(bridge) -> None:
    """Selecting a file fills the diff model with rows QML can render."""
    bridge.selectFile("README.md")
    rows = bridge.diffRows
    assert rows.count > 0
    kinds = {rows.get(i)["kind"] for i in range(rows.count)}
    assert "hunk" in kinds
    assert "line" in kinds
    line = next(rows.get(i) for i in range(rows.count) if rows.get(i)["kind"] == "line")
    assert "markup" in line
    assert bridge.diff["kind"] == "text"
    assert bridge.diff["added"] >= 1


def test_theme_bridge_tracks_selection(qt_app, bridge) -> None:
    from github_desktop.models import ApplicationTheme
    from github_desktop.ui.theme_bridge import ThemeBridge

    theming = ThemeBridge(bridge.store)
    theming.setTheme(ApplicationTheme.DARK.value)
    assert theming.isDark is True
    assert theming.followsSystem is False
    theming.setTheme(ApplicationTheme.LIGHT.value)
    assert theming.isDark is False
    theming.setTheme(ApplicationTheme.SYSTEM.value)
    assert theming.followsSystem is True


def test_icons_resolve_to_something(qt_app) -> None:
    from github_desktop.ui.icons import ICONS, icon_name

    for key in ICONS:
        assert icon_name(key), f"{key} resolved to an empty icon name"


@pytest.mark.skipif(not real_kirigami_available(), reason="Kirigami is not installed")
def test_runs_against_real_kirigami(qt_app, bridge) -> None:
    engine, warnings, flavour = _load_main_window(qt_app, bridge)
    assert flavour == "real"
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    assert window.property("title") == bridge.windowTitle
