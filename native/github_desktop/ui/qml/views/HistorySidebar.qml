// The commit list. Selecting a commit loads its changeset into the diff pane.

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

        Kirigami.SearchField {
            Layout.fillWidth: true
            placeholderText: qsTr("Search commits")
            onTextChanged: app.setHistoryFilter(text)
        }

        Controls.Label {
            visible: app.history.showingChangesFrom !== ""
            text: app.history.showingChangesFrom
            font: Kirigami.Theme.smallFont
            opacity: 0.8
        }
    }

    Kirigami.Separator { Layout.fillWidth: true }

    Controls.ScrollView {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

        ListView {
            id: commitList
            model: app.commits
            clip: true

            // Desktop pages history in as you reach the end of the list.
            onAtYEndChanged: if (atYEnd && count > 0) app.loadMoreCommits()

            Kirigami.PlaceholderMessage {
                anchors.centerIn: parent
                width: parent.width - Kirigami.Units.largeSpacing * 4
                visible: commitList.count === 0
                icon.name: app.iconFor("history")
                text: app.history.emptyMessage
            }

            delegate: Controls.ItemDelegate {
                width: commitList.width
                highlighted: model.isSelected
                onClicked: app.selectCommit(model.sha)

                // Dragging a commit onto the branch button branches from it.
                Drag.active: dragHandler.active
                Drag.mimeData: ({"application/x-github-desktop-commit": model.sha})
                DragHandler {
                    id: dragHandler
                    onActiveChanged: app.setDraggingCommit(active)
                }
                // Desktop highlights the row the diff is showing.
                objectName: model.isSelected ? "commit-highlight" : "commit-row"

                TapHandler {
                    acceptedButtons: Qt.RightButton
                    onTapped: commitMenu.popupFor(model)
                }
                Accessible.name: model.summary + ", " + model.author + ", " + model.relativeTime

                contentItem: RowLayout {
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Avatar {
                        implicitWidth: Kirigami.Units.iconSizes.medium
                        implicitHeight: Kirigami.Units.iconSizes.medium
                        name: model.author
                        source: model.avatarUrl
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        Controls.Label {
                            Layout.fillWidth: true
                            text: model.summary
                            elide: Text.ElideRight
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Kirigami.Units.smallSpacing

                            Controls.Label {
                                Layout.fillWidth: true
                                text: qsTr("%1 · %2").arg(model.author).arg(model.relativeTime)
                                elide: Text.ElideRight
                                opacity: 0.7
                                font: Kirigami.Theme.smallFont
                            }

                            // Desktop `unpushed-indicator`
                            Kirigami.Icon {
                                objectName: "unpushed-indicator"
                                source: app.iconFor("push")
                                visible: model.isLocal
                                opacity: 0.7
                                implicitWidth: Kirigami.Units.iconSizes.small
                                implicitHeight: Kirigami.Units.iconSizes.small
                                Accessible.name: qsTr("This commit has not been pushed to the remote repository")
                            }

                            // Desktop `tag-indicator`
                            Controls.Label {
                                objectName: "tag-indicator"
                                visible: model.tags.length > 0
                                text: app.tagSummary(model.tags)
                                font: Kirigami.Theme.smallFont
                                opacity: 0.8
                                Controls.ToolTip.text: model.tags.join(", ")
                                Controls.ToolTip.visible: hovered
                            }
                        }
                    }

                    Controls.Label {
                        text: model.shortSha
                        font.family: "monospace"
                        opacity: 0.7
                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                    }
                }
            }
        }
    }

    Kirigami.Separator {
        Layout.fillWidth: true
        visible: app.commitFiles.count > 0
    }

    // Files touched by the selected commit.
    Controls.ScrollView {
        Layout.fillWidth: true
        Layout.preferredHeight: Kirigami.Units.gridUnit * 10
        visible: app.commits.count > 0
        Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

        ListView {
            id: commitFileList
            model: app.commitFiles
            clip: true
            Accessible.name: app.section === "history"
                ? qsTr("Selected commit file list")
                : qsTr("Pull request file list")

            Kirigami.PlaceholderMessage {
                anchors.centerIn: parent
                width: parent.width - Kirigami.Units.largeSpacing * 4
                visible: commitFileList.count === 0
                text: app.commits.count > 0 && app.history.hasSelection
                    ? qsTr("No files in commit")
                    : qsTr("No commit selected")
            }

            delegate: Controls.ItemDelegate {
                width: ListView.view.width
                highlighted: model.isSelected
                onClicked: app.selectCommitFile(model.path)
                onDoubleClicked: app.openPath(model.path)

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

    CommitContextMenu { id: commitMenu }
}
