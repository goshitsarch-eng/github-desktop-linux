// First run. The store drives the step; this is the sign-in / skip choice
// Desktop shows before there is anything to look at.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.PlaceholderMessage {
    anchors.centerIn: parent
    width: Math.min(parent.width - Kirigami.Units.gridUnit * 4, Kirigami.Units.gridUnit * 30)

    icon.name: app.iconFor("app")
    text: app.welcomeStep === "AllSet"
        ? qsTr("You're all set!")
        : qsTr("Welcome to %1").arg(app.appName)
    explanation: qsTr("Sign in to your GitHub.com account to clone your repositories, or start with a repository already on this computer.")

    helpfulAction: Kirigami.Action {
        icon.name: app.iconFor("user")
        text: qsTr("Sign in to GitHub")
        onTriggered: app.showPopup("SignIn", {})
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.smallSpacing

        Item { Layout.fillWidth: true }

        Controls.Button {
            text: qsTr("Add a local repository")
            icon.name: app.iconFor("folder-open")
            onClicked: app.showPopup("AddRepository", {})
        }

        Controls.Button {
            text: qsTr("Create your free account.")
            flat: true
            onClicked: app.openUrl("https://github.com/join")
        }

        Controls.Button {
            text: qsTr("Skip for now")
            flat: true
            onClicked: app.finishWelcome()
        }

        Item { Layout.fillWidth: true }
    }
}
