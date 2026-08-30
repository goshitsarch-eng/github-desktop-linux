import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    readonly property string branchName: payload.branch || app.currentBranch

    title: qsTr("Delete branch")
    values: ({"branch": branchName, "includeUpstream": upstreamBox.checked})

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Controls.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: qsTr("Delete the branch “%1”? This cannot be undone.").arg(dialog.branchName)
            wrapMode: Text.WordWrap
        }

        Controls.CheckBox {
            id: upstreamBox
            text: qsTr("Also delete the branch on the remote")
        }
    }
}
