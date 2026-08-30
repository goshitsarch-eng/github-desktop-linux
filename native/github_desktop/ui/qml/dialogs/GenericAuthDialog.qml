import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Authentication required")
    values: ({"host": dialog.payload.host || "", "username": userField.text, "password": passwordField.text})

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Controls.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: qsTr("Enter your credentials for %1.").arg(dialog.payload.host || qsTr("this remote"))
            wrapMode: Text.WordWrap
        }

        Kirigami.FormLayout {
            Layout.fillWidth: true

            Controls.TextField {
                id: userField
                Kirigami.FormData.label: qsTr("Username:")
                text: dialog.payload.username || ""
            }

            Kirigami.PasswordField {
                id: passwordField
                Kirigami.FormData.label: qsTr("Password:")
                onAccepted: dialog.accept()
            }
        }
    }
}
