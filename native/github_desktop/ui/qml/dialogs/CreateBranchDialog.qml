import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Create a branch")
    values: ({"name": nameField.text, "startPoint": startField.currentText})

    Kirigami.FormLayout {
        Controls.TextField {
            id: nameField
            Kirigami.FormData.label: qsTr("Name:")
            text: dialog.payload.name || ""
            onAccepted: dialog.accept()
        }

        Controls.ComboBox {
            id: startField
            Kirigami.FormData.label: qsTr("Based on:")
            model: app.branches
            textRole: "name"
            currentIndex: Math.max(0, app.branches.indexOf("isCurrent", true))
        }
    }
}
