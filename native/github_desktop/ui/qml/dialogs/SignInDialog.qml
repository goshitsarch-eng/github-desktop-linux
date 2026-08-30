// Browser sign-in. Desktop hands off to the system browser and waits for the
// OAuth callback, so this dialog only chooses the endpoint.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Sign in")
    values: ({"endpoint": enterpriseBox.checked ? endpointField.text : ""})

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Controls.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: qsTr("Your browser opens to authorize %1. Come back here when it is done.").arg(app.appName)
            wrapMode: Text.WordWrap
        }

        Controls.CheckBox {
            id: enterpriseBox
            text: qsTr("Sign in to GitHub Enterprise")
        }

        Controls.TextField {
            id: endpointField
            Layout.fillWidth: true
            visible: enterpriseBox.checked
            placeholderText: qsTr("https://github.example.com")
        }
    }
}
