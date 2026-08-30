// The single page the window shows.
//
// Its header carries Desktop's three toolbar controls -- current repository,
// current branch, and the fetch/push/pull button -- and its body switches
// between the welcome flow, the no-repositories blank slate, and the
// repository workspace.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import components

import "views"
import components

Kirigami.Page {
    id: page

    padding: 0
    topPadding: 0
    bottomPadding: 0
    leftPadding: 0
    rightPadding: 0

    titleDelegate: RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing
        visible: app.viewMode === "repository"

        ToolbarDropButton {
            id: repositoryButton
            Layout.preferredWidth: Math.max(Kirigami.Units.gridUnit * 11, implicitWidth)
            label: app.repositoryTitle
            sublabel: qsTr("Current repository")
            iconName: app.iconFor("repository")
            onClicked: repositoryPicker.open()

            // Desktop `onRepositoryToolbarButtonContextMenu`
            TapHandler {
                acceptedButtons: Qt.RightButton
                onTapped: repositoryToolbarMenu.popup()
            }

            Controls.Menu {
                id: repositoryToolbarMenu
                Controls.MenuItem {
                    text: qsTr("Repository settings…")
                    onTriggered: app.showPopup("RepositorySettings", {})
                }
                Controls.MenuItem {
                    text: qsTr("Remove…")
                    onTriggered: app.showPopup("RemoveRepository", {})
                }
            }
        }

        ResizableToolbarButton {
            kind: "branch"
            description: qsTr("Current branch dropdown button")
            enabled: app.repositoryState === "ready"

            ToolbarDropButton {
                id: branchButton
                anchors.fill: parent
                enabled: app.repositoryState === "ready"
                label: app.currentBranch || qsTr("No branch")
                sublabel: qsTr("Current branch")
                iconName: app.iconFor("branch")
                onClicked: branchPicker.open()

                // Desktop `onBranchToolbarButtonContextMenu`
                TapHandler {
                    acceptedButtons: Qt.RightButton
                    onTapped: branchToolbarMenu.popup()
                }

                // Desktop `new-branch-drop`: drag a commit here to branch from it.
                DropArea {
                    objectName: "new-branch-drop"
                    anchors.fill: parent
                    keys: ["application/x-github-desktop-commit"]
                    onDropped: drop => app.showPopup("CreateBranch", {"startPoint": drop.text})
                }

                // Desktop `onMouseEnter` opens the foldout on hover-with-drag.
                HoverHandler {
                    onHoveredChanged: if (hovered && app.draggingCommit) branchPicker.open()
                }

                Controls.Menu {
                    id: branchToolbarMenu
                    Controls.MenuItem {
                        text: qsTr("New branch…")
                        onTriggered: app.showPopup("CreateBranch", {})
                    }
                    Controls.MenuItem {
                        text: qsTr("Rename…")
                        onTriggered: app.showPopup("RenameBranch", {})
                    }
                    Controls.MenuItem {
                        text: qsTr("Delete…")
                        onTriggered: app.showPopup("DeleteBranch", {})
                    }
                }
            }
        }

        Item { Layout.fillWidth: true }

        ResizableToolbarButton {
            kind: "push"
            description: qsTr("Push pull button")
            visible: app.repositoryState === "ready"

            PushPullButton { anchors.fill: parent }
        }
    }

    actions: [
        Kirigami.Action {
            visible: app.viewMode === "repository" && app.hasGitHubRepository
            icon.name: app.checks.icon
            text: qsTr("Pull request checks")
            onTriggered: { app.noteChecksOpened(); checksSheet.open(); }
        },
        Kirigami.Action {
            visible: app.viewMode === "repository" && app.repositoryState === "ready"
            icon.name: app.iconFor("pull-request")
            text: qsTr("Create pull request")
            onTriggered: app.openPullRequest()
        }
    ]

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            Layout.margins: visible ? Kirigami.Units.smallSpacing : 0
            visible: app.banner.visible
            text: app.banner.text
            type: app.banner.severity === "warning"
                ? Kirigami.MessageType.Warning
                : app.banner.severity === "positive"
                    ? Kirigami.MessageType.Positive
                    : Kirigami.MessageType.Information
            actions: Kirigami.Action {
                text: app.banner.actionLabel
                onTriggered: app.activateBanner()
            }
        }

        Loader {
            Layout.fillWidth: true
            Layout.fillHeight: true
            sourceComponent: app.viewMode === "welcome"
                ? welcomeView
                : app.viewMode === "empty" ? emptyView : repositoryView
        }
    }

    Component { id: welcomeView; WelcomeView {} }
    Component { id: emptyView; EmptyStateView {} }
    Component { id: repositoryView; RepositoryView {} }

    RepositoryPicker { id: repositoryPicker }
    BranchPicker { id: branchPicker }
    ChecksSheet { id: checksSheet }
}
