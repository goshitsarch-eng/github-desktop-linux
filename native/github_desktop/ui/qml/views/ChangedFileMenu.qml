// Right-click menu for a changed file. The labels and the rules for which
// entries appear come from ui/menus.py, so they stay in step with Desktop and
// stay testable without a menu on screen.

import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Controls.Menu {
    id: menu

    property var file: null

    function popupFor(model) {
        menu.file = model;
        menu.popup();
    }

    Controls.MenuItem {
        text: qsTr("Discard changes…")
        icon.name: app.iconFor("discard")
        onTriggered: app.showPopup("ConfirmDiscardChanges", {"paths": [menu.file.path]})
    }

    Controls.MenuSeparator {}

    Controls.MenuItem {
        // `Ignore file` for one, `Ignore N selected files` for a selection.
        text: app.ignoreSelectedLabel
        onTriggered: app.ignoreSelectedPaths(menu.file.path)
    }

    Controls.MenuItem {
        text: qsTr("Ignore folder (add to .gitignore)")
        enabled: menu.file && menu.file.directory !== ""
        onTriggered: app.ignorePath(menu.file.path, true)
    }

    Controls.MenuSeparator {}

    Controls.MenuItem {
        text: qsTr("Open in editor")
        icon.name: app.iconFor("editor")
        onTriggered: app.openPath(menu.file.path)
    }

    Controls.MenuItem {
        text: qsTr("Open in default program")
        onTriggered: app.openFileDefault(menu.file.path)
    }

    Controls.MenuItem {
        text: qsTr("Show in file manager")
        icon.name: app.iconFor("folder-open")
        onTriggered: app.revealPath(menu.file.path)
    }

    Controls.MenuSeparator {}

    Controls.MenuItem {
        text: qsTr("Copy file path")
        icon.name: app.iconFor("copy")
        onTriggered: app.copyToClipboard(menu.file.path)
    }
}
