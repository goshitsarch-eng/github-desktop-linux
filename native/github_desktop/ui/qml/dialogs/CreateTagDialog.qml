import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Create a tag")
    values: ({"name": nameField.text, "sha": dialog.payload.sha || ""})

    Kirigami.FormLayout {
        Controls.TextField {
            id: nameField
            Kirigami.FormData.label: qsTr("Name:")
            onAccepted: dialog.accept()
        }

        Controls.Label {
            Kirigami.FormData.label: qsTr("Commit:")
            text: (dialog.payload.sha || "").substring(0, 8)
            font.family: "monospace"
        }
    }
}
