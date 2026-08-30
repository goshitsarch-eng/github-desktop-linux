import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: dialog.payload.heading || qsTr("Push commits")

    Controls.Label {
        Layout.fillWidth: true
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        text: dialog.payload.body || ""
        wrapMode: Text.WordWrap
    }
}
