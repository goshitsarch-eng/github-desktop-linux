// Right-click inside the diff. Discard labels come from ui/diff_view.py so
// they match Desktop's wording for added / removed / modified lines.

import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Controls.Menu {
    id: menu

    property var row: null

    function popupFor(model) {
        menu.row = model;
        menu.popup();
    }

    // Desktop `onContextMenuText`
    Controls.MenuItem {
        text: qsTr("Copy")
        icon.name: app.iconFor("copy")
        onTriggered: app.copyToClipboard(menu.row.text)
    }

    Controls.MenuSeparator {}

    Controls.MenuItem {
        text: app.diff.discardLineLabel
        icon.name: app.iconFor("discard")
        enabled: menu.row && menu.row.selectable
        onTriggered: app.showPopup("ConfirmDiscardSelection", {"path": app.diff.path})
    }

    // Desktop `onContextMenuExpandHunk`
    Controls.MenuItem {
        text: qsTr("Expand whole file")
        enabled: app.diff.canExpandWholeFile
        onTriggered: app.expandWholeFile()
    }
}
