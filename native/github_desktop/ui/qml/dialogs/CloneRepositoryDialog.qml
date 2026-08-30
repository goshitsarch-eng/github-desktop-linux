// "Clone repository": a URL or owner/name, and where to put the checkout.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Clone a repository")
    values: ({
        "url": urlField.text,
        "path": pathField.text,
        "branch": branchField.text
    })

    Kirigami.FormLayout {
        Controls.TextField {
            id: urlField
            Kirigami.FormData.label: qsTr("URL or owner/name:")
            text: dialog.payload.initial_url || dialog.payload.url || ""
            placeholderText: "https://github.com/owner/name"
        }

        FolderField {
            id: pathField
            Kirigami.FormData.label: qsTr("Local path:")
            dialogTitle: qsTr("Clone into")
            text: dialog.payload.path || ""
        }

        Controls.TextField {
            id: branchField
            Kirigami.FormData.label: qsTr("Branch:")
            text: dialog.payload.branch || ""
            placeholderText: qsTr("Optional")
        }
    }
}
