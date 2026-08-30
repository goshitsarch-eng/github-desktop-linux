// Informational popups with nothing to decide.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: payload.title || app.appName
    standardButtons: Controls.Dialog.Close

    Controls.Label {
        Layout.fillWidth: true
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        text: dialog.payload.body || dialog.payload.message || ""
        wrapMode: Text.WordWrap
    }
}
