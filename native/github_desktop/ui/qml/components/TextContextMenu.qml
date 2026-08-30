// Desktop `getDefaultContextMenu` / `onAutocompletingInputContextMenu`: the
// cut/copy/paste menu every text input gets, plus the spellcheck toggle the
// commit fields add on top of it.

import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Controls.Menu {
    id: menu

    property Item field: null
    property bool showSpellcheck: false

    Controls.MenuItem {
        text: qsTr("Undo")
        enabled: menu.field && menu.field.canUndo
        onTriggered: menu.field.undo()
    }
    Controls.MenuItem {
        text: qsTr("Redo")
        enabled: menu.field && menu.field.canRedo
        onTriggered: menu.field.redo()
    }
    Controls.MenuSeparator {}
    Controls.MenuItem {
        text: qsTr("Cut")
        enabled: menu.field && menu.field.selectedText.length > 0
        onTriggered: menu.field.cut()
    }
    Controls.MenuItem {
        text: qsTr("Copy")
        enabled: menu.field && menu.field.selectedText.length > 0
        onTriggered: menu.field.copy()
    }
    Controls.MenuItem {
        text: qsTr("Paste")
        enabled: menu.field && menu.field.canPaste
        onTriggered: menu.field.paste()
    }
    Controls.MenuSeparator {}
    Controls.MenuItem {
        text: qsTr("Select all")
        onTriggered: menu.field.selectAll()
    }
    Controls.MenuSeparator { visible: menu.showSpellcheck }
    Controls.MenuItem {
        visible: menu.showSpellcheck
        text: qsTr("Check spelling")
        checkable: true
        checked: app.settings.spellcheckEnabled
        onTriggered: app.updateSetting("spellcheck_enabled", checked)
    }
}
