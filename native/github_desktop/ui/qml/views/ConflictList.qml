// Conflicted files during a merge / rebase / cherry-pick.
//
// Desktop splits these into `renderUnmergedFile` and `renderResolvedFile`:
// unresolved rows offer the editor and the manual-resolution choices, resolved
// rows offer to undo that choice.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: root

    property var files: []

    spacing: Kirigami.Units.smallSpacing

    Controls.Label {
        Layout.fillWidth: true
        text: app.conflicts.summary
        wrapMode: Text.WordWrap
        opacity: 0.85
    }

    Repeater {
        model: root.files
        delegate: RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: modelData.resolved ? app.iconFor("checks-ok") : app.iconFor("conflict")
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
            }

            Controls.Label {
                Layout.fillWidth: true
                text: modelData.path
                elide: Text.ElideMiddle
                font.family: "monospace"
            }

            // Unresolved: open it, or pick a side.
            Controls.Button {
                visible: !modelData.resolved
                text: qsTr("Open in editor")
                icon.name: app.iconFor("editor")
                onClicked: app.openPath(modelData.path)
            }

            Controls.ToolButton {
                visible: !modelData.resolved && modelData.manualOptions.length > 0
                icon.name: app.iconFor("dropdown")
                display: Controls.AbstractButton.IconOnly
                Accessible.name: qsTr("Resolve using…")
                onClicked: manualMenu.popup()

                // Desktop `getManualResolutionMenuItems`
                Controls.Menu {
                    id: manualMenu
                    Instantiator {
                        model: modelData.manualOptions
                        delegate: Controls.MenuItem {
                            text: modelData.label
                            onTriggered: app.resolveConflict(modelData.path, modelData.value)
                        }
                        onObjectAdded: (index, object) => manualMenu.insertItem(index, object)
                        onObjectRemoved: (index, object) => manualMenu.removeItem(object)
                    }
                }
            }

            // Desktop `makeUndoManualResolutionClickHandler`: put the file
            // back to unresolved so the other side can be chosen instead.
            Controls.ToolButton {
                visible: modelData.resolved && modelData.manualResolution !== ""
                icon.name: app.iconFor("discard")
                display: Controls.AbstractButton.IconOnly
                Accessible.name: qsTr("Undo this resolution")
                onClicked: app.resolveConflict(modelData.path, "")
            }
        }
    }
}
