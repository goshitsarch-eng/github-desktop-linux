// An error the store could not handle silently. Read-only, single button.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: payload.title || qsTr("Error")
    standardButtons: Controls.Dialog.Close
    showCloseButton: false

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Icon {
                source: app.iconFor("error")
                implicitWidth: Kirigami.Units.iconSizes.large
                implicitHeight: Kirigami.Units.iconSizes.large
            }

            Controls.Label {
                Layout.fillWidth: true
                Layout.maximumWidth: Kirigami.Units.gridUnit * 24
                text: dialog.payload.error || dialog.payload.message || qsTr("Something went wrong.")
                wrapMode: Text.WordWrap
                textFormat: Text.PlainText
            }
        }
    }
}
