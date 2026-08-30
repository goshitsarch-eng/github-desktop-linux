// Branches and pull requests for the current repository, as two tabs — the
// same split Desktop puts behind its branch button.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.OverlaySheet {
    id: sheet

    parent: Controls.Overlay.overlay
    title: qsTr("Branches")

    header: ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading { text: sheet.title }

        Controls.TabBar {
            id: tabs
            Layout.fillWidth: true
            Controls.TabButton { text: qsTr("Branches") }
            Controls.TabButton {
                text: qsTr("Pull requests")
                enabled: app.hasGitHubRepository
            }
        }

        Kirigami.SearchField {
            id: filter
            Layout.fillWidth: true
            placeholderText: tabs.currentIndex === 0
                ? qsTr("Filter branches")
                : qsTr("Filter pull requests")
        }
    }

    footer: RowLayout {
        Controls.Button {
            text: qsTr("New branch…")
            icon.name: app.iconFor("branch")
            onClicked: { sheet.close(); app.showPopup("CreateBranch", {}); }
        }
        Item { Layout.fillWidth: true }
    }

    StackLayout {
        implicitWidth: Kirigami.Units.gridUnit * 24
        implicitHeight: Kirigami.Units.gridUnit * 22
        currentIndex: tabs.currentIndex

        ListView {
            id: branchView
            model: app.branches
            clip: true

            section.property: "group"
            section.delegate: Kirigami.ListSectionHeader { width: branchView.width; text: section }

            delegate: Controls.ItemDelegate {
                width: branchView.width
                visible: filter.text === "" || model.name.toLowerCase().includes(filter.text.toLowerCase())
                height: visible ? implicitHeight : 0
                highlighted: model.isCurrent
                onClicked: { app.checkoutBranch(model.name); sheet.close(); }

                TapHandler {
                    acceptedButtons: Qt.RightButton
                    onTapped: branchMenu.popupFor(model)
                }

                contentItem: RowLayout {
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Icon {
                        source: app.iconFor("branch")
                        implicitWidth: Kirigami.Units.iconSizes.small
                        implicitHeight: Kirigami.Units.iconSizes.small
                    }

                    Controls.Label {
                        Layout.fillWidth: true
                        text: model.name
                        elide: Text.ElideMiddle
                        font.bold: model.isCurrent
                    }

                    Controls.Label {
                        text: model.relativeTime
                        opacity: 0.7
                        font: Kirigami.Theme.smallFont
                    }
                }
            }
        }

        ListView {
            id: prView
            model: app.pullRequests
            clip: true

            // Desktop `NoPullRequests`
            Kirigami.PlaceholderMessage {
                objectName: "NoPullRequests"
                anchors.centerIn: parent
                width: parent.width - Kirigami.Units.largeSpacing * 4
                visible: prView.count === 0
                icon.name: app.iconFor("pull-request")
                text: qsTr("No open pull requests in %1").arg(app.repositoryTitle)
                helpfulAction: Kirigami.Action {
                    text: qsTr("Create pull request")
                    icon.name: app.iconFor("pull-request")
                    enabled: app.hasGitHubRepository
                    onTriggered: { sheet.close(); app.openPullRequest(); }
                }
            }

            delegate: Controls.ItemDelegate {
                width: prView.width
                visible: filter.text === "" || model.title.toLowerCase().includes(filter.text.toLowerCase())
                height: visible ? implicitHeight : 0
                onClicked: { app.checkoutPullRequest(model.number); sheet.close(); }
                Accessible.name: qsTr("Switch to pull request #%1").arg(model.number)

                // Desktop's quick view opens on hover.
                HoverHandler {
                    onHoveredChanged: {
                        if (hovered) {
                            quickView.pullRequest = model;
                            quickView.open();
                        } else if (quickView.pullRequest === model) {
                            quickView.close();
                        }
                    }
                }

                // Desktop `onPullRequestItemContextMenu`
                TapHandler {
                    acceptedButtons: Qt.RightButton
                    onTapped: prMenu.popupFor(model)
                }

                contentItem: ColumnLayout {
                    spacing: 0

                    Controls.Label {
                        Layout.fillWidth: true
                        text: model.title
                        elide: Text.ElideRight
                    }

                    Controls.Label {
                        Layout.fillWidth: true
                        text: qsTr("#%1 opened %2 by %3")
                            .arg(model.number).arg(model.relativeTime).arg(model.author)
                        elide: Text.ElideRight
                        opacity: 0.7
                        font: Kirigami.Theme.smallFont
                    }
                }
            }
        }
    }

    PullRequestQuickView { id: quickView }

    Controls.Menu {
        id: branchMenu

        property var branch: null
        function popupFor(model) { branchMenu.branch = model; branchMenu.popup(); }

        Controls.MenuItem {
            text: qsTr("Rename…")
            onTriggered: app.showPopup("RenameBranch", {"branch": branchMenu.branch.name})
        }
        Controls.MenuItem {
            text: qsTr("Delete…")
            icon.name: app.iconFor("delete")
            onTriggered: app.showPopup("DeleteBranch", {"branch": branchMenu.branch.name})
        }
        Controls.MenuSeparator {}
        Controls.MenuItem {
            text: qsTr("Merge into current branch")
            icon.name: app.iconFor("merge")
            onTriggered: app.mergeBranch(branchMenu.branch.name)
        }
        Controls.MenuItem {
            text: qsTr("Squash and merge into current branch")
            icon.name: app.iconFor("merge")
            onTriggered: app.squashMergeBranch(branchMenu.branch.name)
        }
        Controls.MenuSeparator {}
        Controls.MenuItem {
            text: qsTr("View branch on GitHub")
            icon.name: app.iconFor("browser")
            enabled: app.hasGitHubRepository
            onTriggered: app.viewBranchOnGitHub(branchMenu.branch.name)
        }
    }

    Controls.Menu {
        id: prMenu

        property var pullRequest: null
        function popupFor(model) { prMenu.pullRequest = model; prMenu.popup(); }

        Controls.MenuItem {
            text: qsTr("Switch to pull request")
            onTriggered: { app.checkoutPullRequest(prMenu.pullRequest.number); sheet.close(); }
        }
        Controls.MenuItem {
            text: qsTr("View pull request on GitHub")
            icon.name: app.iconFor("browser")
            onTriggered: app.viewPullRequestOnGitHub(prMenu.pullRequest.number)
        }
        Controls.MenuItem {
            text: qsTr("Copy pull request URL")
            icon.name: app.iconFor("copy")
            onTriggered: app.copyPullRequestUrl(prMenu.pullRequest.number)
        }
    }
}
