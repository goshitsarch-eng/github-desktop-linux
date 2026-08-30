import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Remove repository")
    values: ({"deleteFiles": trashBox.checked})

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Controls.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: qsTr("Remove “%1” from %2? The folder stays on disk unless you say otherwise.")
                .arg(app.repositoryTitle).arg(app.appName)
            wrapMode: Text.WordWrap
        }

        Controls.CheckBox {
            id: trashBox
            text: qsTr("Also move this repository to the trash")
        }
    }
}
