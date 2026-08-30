// "New repository": name, where to put it, and the usual git housekeeping.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Create a new repository")
    values: ({
        "name": nameField.text,
        "path": pathField.text + "/" + nameField.text,
        "description": descriptionField.text,
        "createReadme": readmeBox.checked,
        "gitignore": gitignoreBox.currentText === qsTr("None") ? "" : gitignoreBox.currentText,
        "license": licenseBox.currentText === qsTr("None") ? "" : licenseBox.currentText
    })

    Kirigami.FormLayout {
        Controls.TextField {
            id: nameField
            Kirigami.FormData.label: qsTr("Name:")
            text: dialog.payload.name || ""
        }

        Controls.TextField {
            id: descriptionField
            Kirigami.FormData.label: qsTr("Description:")
            placeholderText: qsTr("Optional")
        }

        FolderField {
            id: pathField
            Kirigami.FormData.label: qsTr("Local path:")
            dialogTitle: qsTr("Create repository in")
            text: dialog.payload.path || ""
        }

        Controls.CheckBox {
            id: readmeBox
            Kirigami.FormData.label: qsTr("Initialize with:")
            text: qsTr("README")
        }

        Controls.ComboBox {
            id: gitignoreBox
            Kirigami.FormData.label: qsTr("Git ignore:")
            model: dialog.payload.gitignores || [qsTr("None")]
        }

        Controls.ComboBox {
            id: licenseBox
            Kirigami.FormData.label: qsTr("License:")
            model: dialog.payload.licenses || [qsTr("None")]
        }
    }
}
