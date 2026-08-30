// The diff. Rows come from ui/diff_view.diff_rows_for_qml() already carrying
// their syntax markup and per-line selection state, so this file is layout:
// a gutter with old/new line numbers, and the line body as rich text.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import components

Item {
    id: root

    readonly property var summary: app.diff

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Header: which file, how many lines changed, and the view options.
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.smallSpacing
            visible: root.summary.path !== undefined && root.summary.path !== ""
            spacing: Kirigami.Units.smallSpacing

            Controls.Label {
                Layout.fillWidth: true
                text: root.summary.path || ""
                elide: Text.ElideMiddle
                font.family: "monospace"
            }

            Controls.Label {
                visible: root.summary.added > 0
                text: "+" + root.summary.added
                color: Kirigami.Theme.positiveTextColor
                font: Kirigami.Theme.smallFont
            }

            Controls.Label {
                visible: root.summary.removed > 0
                text: "−" + root.summary.removed
                color: Kirigami.Theme.negativeTextColor
                font: Kirigami.Theme.smallFont
            }

            CopyButton {
                visible: root.summary.sha !== undefined && root.summary.sha !== ""
                copyContent: root.summary.sha || ""
                ariaLabel: root.summary.copyShaLabel || qsTr("Copy SHA")
            }

            Controls.ToolButton {
                icon.name: app.iconFor("settings")
                Accessible.name: qsTr("Diff Options")
                Controls.ToolTip.text: Accessible.name
                Controls.ToolTip.visible: hovered
                onClicked: diffOptions.popup()

                Controls.Menu {
                    id: diffOptions
                    Controls.MenuItem {
                        text: qsTr("Side-by-side")
                        checkable: true
                        checked: root.summary.sideBySide === true
                        onTriggered: app.setSideBySide(checked)
                    }
                    Controls.MenuItem {
                        text: qsTr("Show whitespace changes?")
                        checkable: true
                        checked: root.summary.hideWhitespace !== true
                        onTriggered: app.setHideWhitespace(!checked)
                    }
                    Controls.MenuItem {
                        text: qsTr("Show check marks in the diff")
                        checkable: true
                        checked: app.settings.showDiffCheckMarks
                        onTriggered: app.updateSetting("show_diff_check_marks", checked)
                    }
                    Controls.MenuSeparator {}
                    Controls.MenuItem {
                        text: qsTr("Open in default program")
                        onTriggered: app.openFileDefault(root.summary.path)
                    }
                    // Desktop `renderOpenInExternalEditor`
                    Controls.MenuItem {
                        text: qsTr("Open file in external program.")
                        onTriggered: app.openPath(root.summary.path)
                    }
                }
            }
        }

        Kirigami.Separator {
            Layout.fillWidth: true
            visible: root.summary.path !== undefined && root.summary.path !== ""
        }

        Loader {
            Layout.fillWidth: true
            Layout.fillHeight: true
            sourceComponent: {
                if (root.summary.kind === "none") return blankSlate;
                if (root.summary.kind === "loading") return loadingSlate;
                if (root.summary.tooLarge) return tooLargeSlate;
                if (root.summary.isBinary) return binarySlate;
                if (root.summary.isImage) return imageSlate;
                if (root.summary.isSubmodule) return submoduleSlate;
                return diffLines;
            }
        }
    }

    Component {
        id: diffLines

        ColumnLayout {
            spacing: 0

            // Line selection needs a stable mapping to the unfiltered diff,
            // which hiding whitespace destroys — Desktop disables it too.
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: root.summary.hideWhitespace === true
                type: Kirigami.MessageType.Information
                text: qsTr("Selecting lines is disabled when hiding whitespace changes")
            }

            Controls.ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                ListView {
                    id: lines
                    model: app.diffRows
                    // Desktop keeps the last expanded hunk in view
                    // (`lastExpandedHunk`) so expanding does not jump the diff.
                    onCountChanged: if (app.diff.lastExpandedHunk >= 0)
                        positionViewAtIndex(app.diff.lastExpandedHunk, ListView.Contain)
                    // Diffs are long; recycling keeps scrolling smooth on a big file.
                    reuseItems: true
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: DiffLineDelegate {
                        width: Math.max(lines.width, implicitWidth)
                        showCheckmarks: app.settings.showDiffCheckMarks
                            && root.summary.hideWhitespace !== true
                        onContextMenuRequested: diffMenu.popupFor(model)
                    }
                }
            }
        }
    }

    Component {
        id: tooLargeSlate

        Kirigami.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 4
            icon.name: app.iconFor("diff")
            text: qsTr("The diff is too large to be displayed by default")
            helpfulAction: Kirigami.Action {
                text: qsTr("Show diff")
                icon.name: app.iconFor("diff")
                onTriggered: app.showLargeDiff()
            }
        }
    }

    Component {
        id: blankSlate

        Kirigami.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 4
            visible: text !== ""
            icon.name: app.iconFor("diff")
            text: root.summary.message || ""
        }
    }

    Component {
        id: loadingSlate

        Item {
            Controls.BusyIndicator {
                anchors.centerIn: parent
                running: true
            }
        }
    }

    Component {
        id: binarySlate

        Kirigami.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 4
            icon.name: app.iconFor("binary")
            text: qsTr("This binary file has changed.")
        }
    }

    Component {
        id: imageSlate

        ColumnLayout {
            spacing: Kirigami.Units.smallSpacing

            Controls.TabBar {
                id: imageModes
                Layout.fillWidth: true
                currentIndex: root.summary.imageMode === "Swipe"
                    ? 1
                    : root.summary.imageMode === "OnionSkin"
                        ? 2
                        : root.summary.imageMode === "Difference" ? 3 : 0

                Controls.TabButton {
                    text: qsTr("2-up")
                    onClicked: app.setImageDiffType("TwoUp")
                }
                Controls.TabButton {
                    objectName: "image-diff-swipe"
                    text: qsTr("Swipe")
                    onClicked: app.setImageDiffType("Swipe")
                }
                Controls.TabButton {
                    text: qsTr("Onion skin")
                    onClicked: app.setImageDiffType("OnionSkin")
                }
                Controls.TabButton {
                    // Desktop uses OPERATOR_DIFFERENCE compositing here.
                    objectName: "image-diff-difference"
                    text: qsTr("Difference")
                    onClicked: app.setImageDiffType("Difference")
                }
            }

            Kirigami.PlaceholderMessage {
                Layout.fillWidth: true
                Layout.fillHeight: true
                icon.name: app.iconFor("image")
                text: root.summary.imageMessage || qsTr("This image has changed.")
                explanation: root.summary.imageFooter || ""
                helpfulAction: Kirigami.Action {
                    icon.name: app.iconFor("editor")
                    text: qsTr("Open in external editor")
                    onTriggered: app.openPath(root.summary.path)
                }
            }
        }
    }

    Component {
        id: submoduleSlate

        Kirigami.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 4
            icon.name: app.iconFor("submodule")
            text: qsTr("This submodule has changed.")
            explanation: qsTr("Learn about submodules.")
            helpfulAction: Kirigami.Action {
                text: qsTr("Open repository")
                icon.name: app.iconFor("repository")
                onTriggered: app.openSubmodule(root.summary.path)
            }
        }
    }

    DiffContextMenu { id: diffMenu }
}
