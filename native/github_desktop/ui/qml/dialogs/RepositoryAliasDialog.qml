import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Change alias")
    values: ({"alias": field.text})

    Kirigami.FormLayout {
        Controls.TextField {
            id: field
            Kirigami.FormData.label: qsTr("Alias:")
            text: dialog.payload.alias || app.repositoryTitle
            onAccepted: dialog.accept()
        }
    }
}
