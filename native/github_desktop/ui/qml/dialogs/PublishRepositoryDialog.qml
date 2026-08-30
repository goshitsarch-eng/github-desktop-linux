import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Publish repository")
    values: ({
        "name": nameField.text,
        "description": descriptionField.text,
        "private": privateBox.checked,
        "org": orgBox.currentIndex > 0 ? orgBox.currentText : ""
    })

    Kirigami.FormLayout {
        Controls.TextField {
            id: nameField
            Kirigami.FormData.label: qsTr("Name:")
            text: dialog.payload.name || app.repositoryTitle
        }

        Controls.TextField {
            id: descriptionField
            Kirigami.FormData.label: qsTr("Description:")
            placeholderText: qsTr("Optional")
        }

        Controls.CheckBox {
            id: privateBox
            Kirigami.FormData.label: qsTr("Visibility:")
            text: qsTr("Keep this code private")
            checked: true
        }

        Controls.ComboBox {
            id: orgBox
            Kirigami.FormData.label: qsTr("Owner:")
            model: [dialog.payload.login || qsTr("Your account")].concat(dialog.payload.orgs || [])
        }
    }
}
