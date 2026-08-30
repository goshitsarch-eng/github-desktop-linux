import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Fork behaviour")
    values: ({"forkContributionTarget": field.text})

    Kirigami.FormLayout {
        Controls.TextField {
            id: field
            Kirigami.FormData.label: qsTr("Contribute to:")
            text: dialog.payload.target || "parent"
            onAccepted: dialog.accept()
        }
    }
}
