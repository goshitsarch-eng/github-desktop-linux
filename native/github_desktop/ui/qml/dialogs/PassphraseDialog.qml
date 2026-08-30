// SSH key passphrase and SSH account password share this dialog; only the
// prompt text differs.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: dialog.popupKind === "SSHUserPassword"
        ? qsTr("SSH password")
        : qsTr("SSH key passphrase")
    values: ({"secret": secretField.text, "remember": rememberBox.checked})

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Controls.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: dialog.payload.username
                ? qsTr("Enter the password for %1.").arg(dialog.payload.username)
                : qsTr("Enter the passphrase for %1.").arg(dialog.payload.key_path || qsTr("your SSH key"))
            wrapMode: Text.WordWrap
        }

        Kirigami.PasswordField {
            id: secretField
            Layout.fillWidth: true
            onAccepted: dialog.accept()
        }

        Controls.CheckBox {
            id: rememberBox
            text: qsTr("Remember this in my keyring")
        }
    }
}
