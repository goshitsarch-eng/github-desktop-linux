// No repositories yet. Desktop's blank slate: the three ways in, plus the
// tutorial for people who have never used git.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.PlaceholderMessage {
    anchors.centerIn: parent
    width: Math.min(parent.width - Kirigami.Units.gridUnit * 4, Kirigami.Units.gridUnit * 30)

    icon.name: app.iconFor("repository")
    text: qsTr("Let's get started!")
    explanation: qsTr("Add a repository to GitHub Desktop to start collaborating")

    helpfulAction: Kirigami.Action {
        icon.name: app.iconFor("clone")
        text: qsTr("Clone a repository from the internet…")
        onTriggered: app.showPopup("CloneRepository", {})
    }

    ColumnLayout {
        Layout.fillWidth: true
        Layout.topMargin: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.smallSpacing

        Controls.Button {
            Layout.fillWidth: true
            text: qsTr("Create a new repository on your hard drive…")
            icon.name: app.iconFor("add")
            onClicked: app.showPopup("CreateRepository", {})
        }

        Controls.Button {
            Layout.fillWidth: true
            text: qsTr("Add an existing repository from your hard drive…")
            icon.name: app.iconFor("folder-open")
            onClicked: app.showPopup("AddRepository", {})
        }

        Controls.Button {
            Layout.fillWidth: true
            text: qsTr("Create a tutorial repository…")
            icon.name: app.iconFor("tutorial")
            onClicked: app.showPopup("CreateTutorialRepository", {})
        }

        // Desktop lists the shortcuts alongside the buttons.
        Controls.Label {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.smallSpacing
            text: qsTr("Press %1 to quickly create a new branch from anywhere within the app, "
                     + "%2 to quickly add a local repository, or %3 to clone from anywhere within the app. "
                     + "You can also drag & drop an existing repository folder onto this window.")
                .arg("Ctrl+Shift+N").arg("Ctrl+O").arg("Ctrl+Shift+O")
            wrapMode: Text.WordWrap
            font: Kirigami.Theme.smallFont
            opacity: 0.75
        }
    }

    // Drag & drop an existing repository folder onto the window.
    DropArea {
        anchors.fill: parent
        onDropped: drop => {
            for (let i = 0; i < drop.urls.length; ++i) {
                app.addDroppedPath(drop.urls[i].toString());
            }
        }
    }
}
