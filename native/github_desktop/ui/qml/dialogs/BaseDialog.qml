// Shared behaviour for every popup: it knows its PopupType and payload, sends
// its result back through popups.submit(), and tells the store when the user
// dismisses it so the popup queue drains.

import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.Dialog {
    id: dialog

    property string popupKind: ""
    property var payload: ({})
    /// Title, body and button labels from ui/dialogs.dialog_copy().
    readonly property var copy: popups.copyFor(popupKind, payload)
    /// Values handed to popups.submit() when the primary button is used.
    property var values: ({})
    /// Set by a dialog that has already told the store what to do.
    property bool handled: false

    parent: Controls.Overlay.overlay
    padding: Kirigami.Units.largeSpacing
    preferredWidth: Kirigami.Units.gridUnit * 26
    standardButtons: Controls.Dialog.Ok | Controls.Dialog.Cancel
    title: copy.title || ""

    onAccepted: {
        if (!handled) {
            popups.submit(popupKind, values);
        }
    }
    onRejected: app.closePopup()
}
