// Window-wide key bindings with no visible control of their own. Anything
// that has a button or a menu entry declares its shortcut there instead.

import QtQuick

// Desktop `onGlobalKeyDown`: window-wide keys that stand down while a modal
// is up (`isShowingModal`), because the dialog owns the keyboard then.
Item {
    id: globalKeys

    readonly property bool acceptsKeys: !app.modalOpen
    // Desktop `setFocusChangesNeeded` / `setFocusHistoryNeeded`
    Shortcut {
        sequences: ["Ctrl+1"]
        enabled: globalKeys.acceptsKeys
        onActivated: app.focusSection("changes")
    }
    Shortcut {
        sequences: ["Ctrl+2"]
        enabled: globalKeys.acceptsKeys
        onActivated: app.focusSection("history")
    }
    // Desktop `goToCommitMessage`
    Shortcut {
        sequences: ["Ctrl+G"]
        enabled: globalKeys.acceptsKeys
        onActivated: app.goToCommitMessage()
    }
    // Desktop `onSelectAll` -> `selectAllWindowContents` / `selectAllChildren`
    Shortcut {
        sequences: [StandardKey.SelectAll]
        enabled: globalKeys.acceptsKeys && !app.modalOpen
        onActivated: app.selectAllVisible()
    }
    Shortcut { sequences: ["Ctrl+P"]; onActivated: app.push() }
    Shortcut { sequences: ["Ctrl+Shift+P"]; onActivated: app.pull() }
    Shortcut { sequences: ["Ctrl+Shift+T"]; onActivated: app.fetch() }
    Shortcut { sequences: ["Ctrl+R"]; onActivated: app.openPullRequest() }
    Shortcut { sequences: ["Ctrl+Shift+N"]; onActivated: app.showPopup("CreateBranch", {}) }
    Shortcut { sequences: ["Ctrl+Shift+R"]; onActivated: app.showPopup("RenameBranch", {}) }
    Shortcut { sequences: ["Ctrl+Shift+D"]; onActivated: app.showPopup("DeleteBranch", {}) }
    Shortcut { sequences: ["Ctrl+Shift+S"]; onActivated: app.stashChanges() }
    Shortcut { sequences: ["Ctrl+H"]; onActivated: app.toggleStash() }
    Shortcut {
        sequences: ["Ctrl+Shift+Backspace"]
        onActivated: app.showPopup("ConfirmDiscardChanges", {"discardingAll": true})
    }
    Shortcut {
        sequences: ["Ctrl+=", "Ctrl++"]
        onActivated: app.setZoom(Math.min(3.0, app.settings.zoomFactor + 0.1))
    }
    Shortcut {
        sequences: ["Ctrl+-"]
        onActivated: app.setZoom(Math.max(0.5, app.settings.zoomFactor - 0.1))
    }
    Shortcut { sequences: ["Ctrl+0"]; onActivated: app.setZoom(1.0) }
}
