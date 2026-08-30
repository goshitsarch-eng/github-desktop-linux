// One diff row: line numbers, an optional include checkbox, and the body.
//
// Additions and deletions get Breeze's positive/negative background at low
// opacity so the colours track the user's scheme instead of being hard-coded.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Item {
    id: row

    property bool showCheckmarks: true

    signal contextMenuRequested()

    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: row.contextMenuRequested()
    }

    readonly property bool isHunk: model.kind === "hunk"
    readonly property bool isAdd: model.lineType === "Add"
    readonly property bool isDelete: model.lineType === "Delete"

    implicitHeight: content.implicitHeight + Kirigami.Units.smallSpacing
    implicitWidth: content.implicitWidth

    Rectangle {
        anchors.fill: parent
        color: {
            if (row.isHunk) return Kirigami.Theme.alternateBackgroundColor;
            if (row.isAdd) return Kirigami.Theme.positiveBackgroundColor;
            if (row.isDelete) return Kirigami.Theme.negativeBackgroundColor;
            return "transparent";
        }
    }

    RowLayout {
        id: content
        anchors.fill: parent
        anchors.leftMargin: Kirigami.Units.smallSpacing
        anchors.rightMargin: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing

        Controls.CheckBox {
            visible: row.showCheckmarks && model.selectable
            checked: model.included
            implicitWidth: Kirigami.Units.iconSizes.small
            Accessible.name: qsTr("Include this line in the commit")
            onClicked: app.setLineIncluded(model.diffIndex, checked)
        }

        Controls.Label {
            visible: !row.isHunk
            text: model.oldNumber > 0 ? model.oldNumber : ""
            horizontalAlignment: Text.AlignRight
            Layout.preferredWidth: Kirigami.Units.gridUnit * 2
            font.family: "monospace"
            opacity: 0.55
        }

        Controls.Label {
            visible: !row.isHunk
            text: model.newNumber > 0 ? model.newNumber : ""
            horizontalAlignment: Text.AlignRight
            Layout.preferredWidth: Kirigami.Units.gridUnit * 2
            font.family: "monospace"
            opacity: 0.55
        }

        Controls.Label {
            visible: !row.isHunk
            text: row.isAdd ? "+" : row.isDelete ? "−" : " "
            font.family: "monospace"
            opacity: 0.7
        }

        Controls.Label {
            Layout.fillWidth: true
            text: row.isHunk ? model.text : model.markup
            textFormat: row.isHunk ? Text.PlainText : Text.RichText
            font.family: "monospace"
            opacity: row.isHunk ? 0.7 : 1.0
            elide: Text.ElideNone
        }

        Controls.ToolButton {
            visible: row.isHunk && model.expansion !== "None"
            icon.name: app.iconFor("expand")
            display: Controls.AbstractButton.IconOnly
            Accessible.name: qsTr("Expand this hunk")
            onClicked: app.expandHunk(model.hunkIndex, model.expansion)
        }
    }
}
