import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Create a tutorial repository")

    Controls.Label {
        Layout.fillWidth: true
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        text: qsTr("A small repository to learn the basics: making a branch, editing a file, committing, and opening a pull request.")
        wrapMode: Text.WordWrap
        textFormat: Text.RichText
        onLinkActivated: link => app.openUrl(link)
    }
}
