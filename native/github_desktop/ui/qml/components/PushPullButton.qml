// The fetch / push / pull control. What it says, whether it is enabled and
// what clicking it does all come from `app.pushPull`, which is
// `push_pull.describe_push_pull()` — the same branching Desktop uses.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

RowLayout {
    id: root

    readonly property var state: app.pushPull
    spacing: 0

    Controls.ToolButton {
        Layout.fillWidth: true
        enabled: root.state.enabled
        Accessible.name: root.state.label
        Controls.ToolTip.text: root.state.description
        Controls.ToolTip.visible: hovered && root.state.description !== ""
        Controls.ToolTip.delay: Kirigami.Units.toolTipDelay
        onClicked: app.runPushPull()

        contentItem: RowLayout {
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: root.state.icon
                visible: !root.state.busy
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
            }

            Controls.BusyIndicator {
                visible: root.state.busy
                running: root.state.busy
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0

                Controls.Label {
                    Layout.fillWidth: true
                    text: root.state.label
                    elide: Text.ElideRight
                    horizontalAlignment: Text.AlignLeft
                }

                Controls.Label {
                    objectName: "push-last-fetched"
                    Layout.fillWidth: true
                    text: root.state.description
                    elide: Text.ElideRight
                    opacity: 0.7
                    font: Kirigami.Theme.smallFont
                    horizontalAlignment: Text.AlignLeft
                }
            }

            Controls.Label {
                text: root.state.aheadBehind
                visible: text !== ""
                font: Kirigami.Theme.smallFont
                opacity: 0.9
            }
        }
    }

    Controls.ToolButton {
        visible: root.state.menuItems.length > 0
        icon.name: "arrow-down"
        Accessible.name: qsTr("More push options")
        onClicked: pushMenu.popup()

        Controls.Menu {
            id: pushMenu
            Instantiator {
                model: root.state.menuItems
                delegate: Controls.MenuItem {
                    text: modelData
                    onTriggered: modelData === "force-push" ? app.forcePush() : app.fetch()
                }
                onObjectAdded: (index, object) => pushMenu.insertItem(index, object)
                onObjectRemoved: (index, object) => pushMenu.removeItem(object)
            }
        }
    }

    // The progress of a running fetch/push/pull, under the button like Desktop.
    Controls.ProgressBar {
        Layout.fillWidth: true
        Layout.maximumWidth: parent.width
        visible: root.state.busy && root.state.progress > 0
        value: root.state.progress
    }
}
