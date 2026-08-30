// Right-click on a commit. Undo is only offered for the tip commit, and only
// while nothing else is rewriting the repository.

import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Controls.Menu {
    id: menu

    property var commit: null

    function popupFor(model) {
        menu.commit = model;
        menu.popup();
    }

    Controls.MenuItem {
        text: qsTr("Undo commit?")
        icon.name: app.iconFor("discard")
        enabled: app.history.canUndo
        // Desktop: "Undo is disabled while the repository is being updated"
        Controls.ToolTip.text: enabled
            ? ""
            : qsTr("Undo is disabled while the repository is being updated")
        Controls.ToolTip.visible: hovered && !enabled
        onTriggered: app.undoCommit()
    }

    Controls.MenuItem {
        text: qsTr("Revert this commit")
        onTriggered: app.revertCommit(menu.commit.sha)
    }

    Controls.MenuSeparator {}

    Controls.MenuItem {
        text: app.previousTagsLabel
        visible: menu.commit && menu.commit.tags.length > 0
        enabled: false
    }

    Controls.MenuItem {
        text: qsTr("Create a tag…")
        icon.name: app.iconFor("tag")
        onTriggered: app.showPopup("CreateTag", {"sha": menu.commit.sha})
    }

    Controls.MenuItem {
        text: qsTr("Create a branch from this commit")
        icon.name: app.iconFor("branch")
        onTriggered: app.showPopup("CreateBranch", {"startPoint": menu.commit.sha})
    }

    Controls.MenuItem {
        text: qsTr("Check out this commit")
        onTriggered: app.showPopup("ConfirmCheckoutCommit", {"sha": menu.commit.sha})
    }

    Controls.MenuItem {
        text: app.squashLabel
        visible: app.selectedCommitCount > 1
        onTriggered: app.showPopup("MultiCommitOperation", {"kind": "Squash"})
    }

    Controls.MenuSeparator {}

    Controls.MenuItem {
        text: app.copyShaLabel
        icon.name: app.iconFor("copy")
        onTriggered: app.copyToClipboard(menu.commit.sha)
    }

    Controls.MenuItem {
        text: qsTr("View on GitHub")
        icon.name: app.iconFor("browser")
        enabled: app.hasGitHubRepository
        onTriggered: app.viewCommitOnGitHub(menu.commit.sha)
    }
}
