// "Add local repository": pick a folder that already holds a git repository.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Add local repository")
    values: ({"path": pathField.text})

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Kirigami.FormLayout {
            Layout.fillWidth: true

            FolderField {
                id: pathField
                Kirigami.FormData.label: qsTr("Local path:")
                Layout.fillWidth: true
                dialogTitle: qsTr("Add local repository")
                text: dialog.payload.path || ""
                placeholder: qsTr("Path to a Git repository")
            }
        }

        Controls.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: qsTr("The folder must already contain a Git repository. To start a new one, use New repository instead.")
            wrapMode: Text.WordWrap
            opacity: 0.8
            font: Kirigami.Theme.smallFont
        }
    }
}
