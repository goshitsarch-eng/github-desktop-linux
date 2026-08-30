// The application menu. Kirigami's GlobalDrawer in `isMenu` mode is the
// desktop-shaped variant: a menu off the hamburger rather than a sliding
// pane. The entries mirror ui/actions.py so the menu, the shortcuts and the
// enable/disable rules stay in step.

import QtQuick
import org.kde.kirigami as Kirigami

Kirigami.GlobalDrawer {
    id: drawer

    title: app.appName
    titleIcon: app.iconFor("app")
    isMenu: true

    actions: [
        Kirigami.Action {
            text: qsTr("New repository…")
            icon.name: app.iconFor("add")
            shortcut: "Ctrl+N"
            onTriggered: app.showPopup("CreateRepository", {})
        },
        Kirigami.Action {
            text: qsTr("Add local repository…")
            icon.name: app.iconFor("folder-open")
            shortcut: "Ctrl+O"
            onTriggered: app.showPopup("AddRepository", {})
        },
        Kirigami.Action {
            text: qsTr("Clone repository…")
            icon.name: app.iconFor("clone")
            shortcut: "Ctrl+Shift+O"
            onTriggered: app.showPopup("CloneRepository", {})
        },
        Kirigami.Action { separator: true },
        Kirigami.Action {
            text: qsTr("Open in editor")
            icon.name: app.iconFor("editor")
            shortcut: "Ctrl+Shift+A"
            enabled: app.repositoryState === "ready"
            onTriggered: app.openInEditor()
        },
        Kirigami.Action {
            text: qsTr("Open in terminal")
            icon.name: app.iconFor("terminal")
            shortcut: "Ctrl+`"
            enabled: app.repositoryState === "ready"
            onTriggered: app.openInShell()
        },
        Kirigami.Action {
            text: qsTr("Show in file manager")
            icon.name: app.iconFor("folder-open")
            shortcut: "Ctrl+Shift+F"
            enabled: app.repositoryState === "ready"
            onTriggered: app.openWorkingDirectory()
        },
        Kirigami.Action {
            text: qsTr("View on GitHub")
            icon.name: app.iconFor("browser")
            shortcut: "Ctrl+Shift+G"
            enabled: app.hasGitHubRepository
            onTriggered: app.viewOnGitHub()
        },
        Kirigami.Action { separator: true },
        Kirigami.Action {
            text: qsTr("Repository settings…")
            icon.name: app.iconFor("settings")
            enabled: app.repositoryState === "ready"
            onTriggered: app.showPopup("RepositorySettings", {})
        },
        Kirigami.Action {
            text: qsTr("Remove repository…")
            icon.name: app.iconFor("remove")
            enabled: app.repositoryState !== "none"
            onTriggered: app.showPopup("RemoveRepository", {})
        },
        Kirigami.Action { separator: true },
        Kirigami.Action {
            text: qsTr("Settings…")
            icon.name: app.iconFor("settings")
            shortcut: "Ctrl+,"
            onTriggered: app.showPopup("Preferences", {})
        },
        Kirigami.Action {
            text: qsTr("About %1").arg(app.appName)
            icon.name: app.iconFor("help")
            onTriggered: app.showPopup("About", {})
        },
        Kirigami.Action {
            text: qsTr("Quit")
            icon.name: "application-exit"
            shortcut: StandardKey.Quit
            onTriggered: Qt.quit()
        }
    ]
}
