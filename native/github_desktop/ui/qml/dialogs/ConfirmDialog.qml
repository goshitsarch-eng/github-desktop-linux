// The plain yes/no popup. Most of Desktop's confirmations differ only in their
// wording, which ui/dialogs.dialog_copy() supplies from the popup type.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: copy.title || payload.title || qsTr("Are you sure?")
    values: ({"dontAskAgain": dontAsk.checked})

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Controls.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: dialog.copy.body || dialog.payload.body || dialog.payload.message || ""
            wrapMode: Text.WordWrap
            visible: text !== ""
        }

        Controls.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: dialog.copy.note || ""
            wrapMode: Text.WordWrap
            visible: text !== ""
            opacity: 0.8
            font: Kirigami.Theme.smallFont
        }

        Controls.CheckBox {
            id: dontAsk
            visible: dialog.copy.checkLabel !== undefined && dialog.copy.checkLabel !== ""
            text: dialog.copy.checkLabel || ""
        }
    }
}
