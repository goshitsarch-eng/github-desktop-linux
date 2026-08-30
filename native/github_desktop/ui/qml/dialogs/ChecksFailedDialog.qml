import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Checks failed")

    Controls.Label {
        Layout.fillWidth: true
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        text: dialog.payload.body || qsTr("Some checks on this pull request did not pass.")
        wrapMode: Text.WordWrap
        textFormat: Text.RichText
        onLinkActivated: link => app.openUrl(link)
    }
}
