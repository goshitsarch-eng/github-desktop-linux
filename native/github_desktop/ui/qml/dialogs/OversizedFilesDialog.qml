import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Large files detected")

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Controls.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: qsTr("These files are over 100 MB. GitHub rejects a push that contains them unless they are tracked with Git LFS.")
            wrapMode: Text.WordWrap
        }

        Repeater {
            model: dialog.payload.files || []
            delegate: Controls.Label {
                Layout.fillWidth: true
                text: modelData
                elide: Text.ElideMiddle
                font.family: "monospace"
            }
        }
    }
}
