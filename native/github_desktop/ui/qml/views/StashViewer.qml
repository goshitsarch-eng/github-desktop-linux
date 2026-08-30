// Stashed changes: the file list from the stash, and what to do with it.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: root
    spacing: 0

    RowLayout {
        Layout.fillWidth: true
        Layout.margins: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading {
            Layout.fillWidth: true
            level: 4
            text: qsTr("Stashed Changes")
        }

        Controls.Button {
            text: qsTr("Restore")
            icon.name: app.iconFor("stash")
            onClicked: app.restoreStash()
        }

        Controls.Button {
            text: qsTr("Discard")
            icon.name: app.iconFor("discard")
            onClicked: app.showPopup("ConfirmDiscardStash", {})
        }
    }

    Kirigami.Separator { Layout.fillWidth: true }

    Controls.ScrollView {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

        ListView {
            id: stashFiles
            model: app.stashedFiles
            clip: true
            Accessible.name: qsTr("Stash file list")

            Kirigami.PlaceholderMessage {
                anchors.centerIn: parent
                width: parent.width - Kirigami.Units.largeSpacing * 4
                visible: stashFiles.count === 0
                icon.name: app.iconFor("stash")
                text: qsTr("No stashed changes")
            }

            delegate: Controls.ItemDelegate {
                width: stashFiles.width
                highlighted: model.isSelected
                onClicked: app.selectStashedFile(model.path)

                contentItem: RowLayout {
                    spacing: Kirigami.Units.smallSpacing

                    Controls.Label {
                        Layout.fillWidth: true
                        text: model.name
                        elide: Text.ElideMiddle
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
        }
    }
}
