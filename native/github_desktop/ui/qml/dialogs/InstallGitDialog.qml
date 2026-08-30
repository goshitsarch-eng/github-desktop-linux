import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Git not found")
    standardButtons: Controls.Dialog.Close

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Controls.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: qsTr("%1 needs Git on your PATH. Install it with your distribution's package manager, then restart the app.")
                .arg(app.appName)
            wrapMode: Text.WordWrap
        }

        Controls.Label {
            Layout.fillWidth: true
            text: "sudo apt install git\nsudo dnf install git\nsudo pacman -S git"
            font.family: "monospace"
            opacity: 0.8
        }
    }
}
