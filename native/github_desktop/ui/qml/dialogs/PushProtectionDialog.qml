import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Secret detected")

    Controls.Label {
        Layout.fillWidth: true
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        text: dialog.payload.body || qsTr("GitHub blocked this push because it contains a secret.")
        wrapMode: Text.WordWrap
        textFormat: Text.RichText
        onLinkActivated: link => app.openUrl(link)
    }
}
