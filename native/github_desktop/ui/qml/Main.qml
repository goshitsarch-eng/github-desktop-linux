// The application window.
//
// Kirigami.ApplicationWindow gives us the KDE shell: a global drawer for the
// application menu, the page stack, and the platform's own window chrome.
// Everything binds to `app` (github_desktop.ui.bridge.AppBridge), which
// re-emits the store's single `changed` signal, so a property here is just a
// getter that Qt re-evaluates when the store moves.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.ApplicationWindow {
    id: root

    title: app.windowTitle
    width: app.settings.windowWidth
    height: app.settings.windowHeight
    minimumWidth: Kirigami.Units.gridUnit * 38
    minimumHeight: Kirigami.Units.gridUnit * 22

    signal commitMessageFocusRequested()

    onClosing: {
        app.saveWindowSize(root.width, root.height);
        app.flush();
    }

    globalDrawer: AppDrawer {}
    pageStack.initialPage: MainPage {}

    Connections {
        target: app
        function onWindowInfo(text, holdMs) { overlayHint.show(text, holdMs); }
        function onPopupRequested(type, payload) { dialogHost.openPopup(type, payload); }
        function onCommitMessageFocusRequested() { root.commitMessageFocusRequested(); }
        function onToast(message) { root.showPassiveNotification(message); }
    }

    DialogHost { id: dialogHost }
    AppShortcuts {}

    // Desktop `FullScreenInfo`: F11 toggles, and says so once on the way in.
    Shortcut {
        sequences: ["F11"]
        onActivated: {
            if (root.visibility === Window.FullScreen) {
                root.visibility = Window.Windowed;
            } else {
                root.visibility = Window.FullScreen;
                overlayHint.show(qsTr("Press F11 to exit fullscreen"), 3000);
            }
        }
    }

    Controls.Action {
        id: fullScreenAction
        text: qsTr("Toggle full screen")
        shortcut: "F11"
    }

    // Desktop `ZoomInfo` / `FullScreenInfo`: a brief centred overlay.
    Controls.Popup {
        id: overlayHint
        objectName: "window-zoom-info"

        function show(text, holdMs) {
            hintLabel.text = text;
            hintTimer.interval = Math.max(400, holdMs);
            open();
            hintTimer.restart();
        }

        x: Math.round((root.width - width) / 2)
        y: Kirigami.Units.gridUnit * 3
        modal: false
        focus: false
        closePolicy: Controls.Popup.NoAutoClose
        padding: Kirigami.Units.largeSpacing

        Controls.Label { id: hintLabel }
        Timer { id: hintTimer; onTriggered: overlayHint.close() }
    }
}
