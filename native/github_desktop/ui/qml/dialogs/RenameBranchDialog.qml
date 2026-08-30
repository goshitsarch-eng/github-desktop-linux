import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Rename branch")
    values: ({"from": dialog.payload.branch || app.currentBranch, "name": nameField.text})

    Kirigami.FormLayout {
        Controls.TextField {
            id: nameField
            Kirigami.FormData.label: qsTr("New name:")
            text: dialog.payload.branch || app.currentBranch
            onAccepted: dialog.accept()
        }
    }
}
