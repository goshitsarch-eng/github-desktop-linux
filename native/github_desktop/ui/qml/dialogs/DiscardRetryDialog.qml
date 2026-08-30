import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Could not discard changes")

    Controls.Label {
        Layout.fillWidth: true
        Layout.maximumWidth: Kirigami.Units.gridUnit * 24
        text: dialog.payload.error || qsTr("The changes could not be moved to the trash. Try again, or delete them permanently.")
        wrapMode: Text.WordWrap
        textFormat: Text.RichText
        onLinkActivated: link => app.openUrl(link)
    }
}
