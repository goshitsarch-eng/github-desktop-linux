// The repository chooser. Kirigami's OverlaySheet is the right shape for a
// list that drops out of a toolbar button: it dims the window, closes on
// Escape, and sizes to its content.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.OverlaySheet {
    id: sheet

    parent: Controls.Overlay.overlay
    title: qsTr("Repositories")

    header: ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading { text: sheet.title }

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Kirigami.SearchField {
                Layout.fillWidth: true
                placeholderText: qsTr("Filter your repositories")
                onTextChanged: app.setRepositoryFilter(text)
            }

            Controls.ToolButton {
                icon.name: app.iconFor("fetch")
                display: Controls.AbstractButton.IconOnly
                Accessible.name: qsTr("Refresh the list of repositories")
                Controls.ToolTip.text: Accessible.name
                Controls.ToolTip.visible: hovered
                onClicked: app.refreshRepositories()
            }
        }
    }

    footer: RowLayout {
        Controls.Button {
            objectName: "new-repository-button"
            text: qsTr("New…")
            icon.name: app.iconFor("add")
            onClicked: { sheet.close(); app.showPopup("CreateRepository", {}); }

            // Desktop `onNewRepositoryButtonKeyDown`: Down opens the menu of
            // ways to add a repository rather than activating the default.
            Keys.onDownPressed: newRepositoryMenu.popup()

            Controls.Menu {
                id: newRepositoryMenu
                Controls.MenuItem {
                    text: qsTr("Create a new repository…")
                    onTriggered: { sheet.close(); app.showPopup("CreateRepository", {}); }
                }
                Controls.MenuItem {
                    text: qsTr("Add an existing repository…")
                    onTriggered: { sheet.close(); app.showPopup("AddRepository", {}); }
                }
                Controls.MenuItem {
                    text: qsTr("Clone a repository…")
                    onTriggered: { sheet.close(); app.showPopup("CloneRepository", {}); }
                }
            }
        }
        Controls.Button {
            text: qsTr("Add…")
            icon.name: app.iconFor("folder-open")
            onClicked: { sheet.close(); app.showPopup("AddRepository", {}); }
        }
        Controls.Button {
            text: qsTr("Clone…")
            icon.name: app.iconFor("clone")
            onClicked: { sheet.close(); app.showPopup("CloneRepository", {}); }
        }
        Item { Layout.fillWidth: true }
    }

    ListView {
        id: view
        // Desktop keys the foldout width off the sidebar, with a floor.
        implicitWidth: app.foldoutWidth
        implicitHeight: Kirigami.Units.gridUnit * 22
        model: app.repositories
        clip: true

        section.property: "group"
        section.delegate: Kirigami.ListSectionHeader { width: view.width; text: section }

        Kirigami.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.largeSpacing * 4
            visible: view.count === 0
            icon.name: app.iconFor("repository")
            text: qsTr("No repositories")
            helpfulAction: Kirigami.Action {
                text: qsTr("Add a local repository")
                icon.name: app.iconFor("folder-open")
                onTriggered: { sheet.close(); app.showPopup("AddRepository", {}); }
            }
        }

        delegate: Controls.ItemDelegate {
            width: view.width
            enabled: !model.isCloning
            onClicked: { app.selectRepository(model.repoId); sheet.close(); }

            // Desktop `onRepositoryToolbarButtonContextMenu`
            TapHandler {
                acceptedButtons: Qt.RightButton
                onTapped: repositoryMenu.popupFor(model)
            }
            Controls.ToolTip.text: model.tooltip
            Controls.ToolTip.visible: hovered && model.tooltip !== ""

            contentItem: RowLayout {
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Icon {
                    source: model.icon
                    implicitWidth: Kirigami.Units.iconSizes.small
                    implicitHeight: Kirigami.Units.iconSizes.small
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0

                    Controls.Label {
                        Layout.fillWidth: true
                        text: model.name
                        elide: Text.ElideRight
                    }

                    Controls.Label {
                        Layout.fillWidth: true
                        text: model.tooltip
                        elide: Text.ElideMiddle
                        opacity: 0.7
                        font: Kirigami.Theme.smallFont
                    }
                }

                // Desktop `repo-changes-dot`
                Kirigami.Icon {
                    objectName: "repo-changes-dot"
                    source: app.iconFor("changes")
                    visible: model.hasChanges
                    opacity: 0.7
                    implicitWidth: Kirigami.Units.iconSizes.small
                    implicitHeight: Kirigami.Units.iconSizes.small
                    Accessible.name: qsTr("Has uncommitted changes")
                }

                Controls.Label {
                    text: model.aheadBehind
                    visible: text !== ""
                    font: Kirigami.Theme.smallFont
                    opacity: 0.8
                }
            }
        }
    }

    Controls.Menu {
        id: repositoryMenu

        property var repository: null
        function popupFor(model) { repositoryMenu.repository = model; repositoryMenu.popup(); }

        Controls.MenuItem {
            text: qsTr("Open in editor")
            icon.name: app.iconFor("editor")
            onTriggered: { app.selectRepository(repositoryMenu.repository.repoId); app.openInEditor(); }
        }
        Controls.MenuItem {
            text: qsTr("Show in file manager")
            icon.name: app.iconFor("folder-open")
            onTriggered: { app.selectRepository(repositoryMenu.repository.repoId); app.openWorkingDirectory(); }
        }
        Controls.MenuSeparator {}
        Controls.MenuItem {
            text: qsTr("Choose a new alias for the repository")
            onTriggered: app.showPopup("ChangeRepositoryAlias", {"repoId": repositoryMenu.repository.repoId})
        }
        Controls.MenuItem {
            text: qsTr("Remove…")
            icon.name: app.iconFor("remove")
            onTriggered: {
                app.selectRepository(repositoryMenu.repository.repoId);
                app.showPopup("RemoveRepository", {});
            }
        }
    }
}
