import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Switch branch")

    Controls.Label {
        Layout.fillWidth: true
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        text: qsTr("You have uncommitted changes. Stash them and switch, or bring them with you?")
        wrapMode: Text.WordWrap
        textFormat: Text.RichText
        onLinkActivated: link => app.openUrl(link)
    }
}
