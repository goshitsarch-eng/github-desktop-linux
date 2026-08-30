// One row in the changed-files list: an include checkbox, the file name with
// its directory, and the git status letter in a status color.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Controls.ItemDelegate {
    id: delegate

    signal opened()
    signal inclusionToggled()
    signal openRequested()
    signal contextMenuRequested()

    highlighted: model.isSelected
    onClicked: delegate.opened()
    onDoubleClicked: delegate.openRequested()

    // Desktop opens its context menu on right-click anywhere in the row.
    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: delegate.contextMenuRequested()
    }
    Accessible.name: model.path + " " + model.statusKind

    contentItem: RowLayout {
        spacing: Kirigami.Units.smallSpacing

        Controls.CheckBox {
            checkState: model.included === 1
                ? Qt.Checked
                : model.included === 2 ? Qt.PartiallyChecked : Qt.Unchecked
            Accessible.name: qsTr("Include %1 in the commit").arg(model.path)
            onClicked: delegate.inclusionToggled()
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0

            Controls.Label {
                Layout.fillWidth: true
                text: model.name
                elide: Text.ElideMiddle
            }

            Controls.Label {
                Layout.fillWidth: true
                visible: model.directory !== ""
                text: model.directory
                elide: Text.ElideMiddle
                opacity: 0.7
                font: Kirigami.Theme.smallFont
            }
        }

        Kirigami.Icon {
            source: app.iconFor("conflict")
            visible: model.isConflicted
            implicitWidth: Kirigami.Units.iconSizes.small
            implicitHeight: Kirigami.Units.iconSizes.small
        }

        Controls.Label {
            text: model.statusLetter
            font.family: "monospace"
            color: model.statusColor === "positive"
                ? Kirigami.Theme.positiveTextColor
                : model.statusColor === "negative"
                    ? Kirigami.Theme.negativeTextColor
                    : Kirigami.Theme.neutralTextColor
        }
    }
}
