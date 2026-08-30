import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Discard changes")
    values: ({
        "paths": dialog.payload.paths || [],
        "discardingAll": dialog.payload.discarding_all === true,
        "permanent": permanentBox.checked,
        "dontAskAgain": dontAskBox.checked
    })

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Controls.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: dialog.payload.discarding_all
                ? qsTr("Discard every uncommitted change in this repository?")
                : qsTr("Discard the changes to the selected files?")
            wrapMode: Text.WordWrap
        }

        Controls.CheckBox {
            id: permanentBox
            text: qsTr("Delete permanently instead of moving to the trash")
        }

        Controls.CheckBox {
            id: dontAskBox
            text: qsTr("Don't ask me again")
        }
    }
}
