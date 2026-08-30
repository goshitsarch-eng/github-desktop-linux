import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Unknown SSH host")
    values: ({"accept": true})

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Controls.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: qsTr("The authenticity of “%1” can't be established. Add it to your known hosts?")
                .arg(dialog.payload.host || "")
            wrapMode: Text.WordWrap
        }

        Controls.Label {
            Layout.fillWidth: true
            text: dialog.payload.fingerprint || ""
            font.family: "monospace"
            wrapMode: Text.WrapAnywhere
            opacity: 0.8
        }
    }
}
