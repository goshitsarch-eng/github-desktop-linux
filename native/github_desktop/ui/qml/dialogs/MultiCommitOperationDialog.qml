// Merge, rebase, cherry-pick and squash all run through this one flow, with
// the conflict step in the middle. merge_cta_message() in ui/multi_commit.py
// decides the wording; this shows it and offers the two ways out.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

import "../views"

BaseDialog {
    id: dialog

    readonly property bool conflicts: payload.step === "conflicts"

    title: payload.title || qsTr("Merge")
    standardButtons: Controls.Dialog.NoButton

    customFooterActions: [
        Kirigami.Action {
            text: dialog.conflicts ? qsTr("Continue") : (dialog.payload.start_label || qsTr("Start"))
            icon.name: app.iconFor("merge")
            enabled: !dialog.conflicts || dialog.payload.can_continue !== false
            onTriggered: { popups.submit(dialog.popupKind, dialog.values); dialog.close(); }
        },
        Kirigami.Action {
            text: dialog.conflicts ? qsTr("Abort") : qsTr("Cancel")
            icon.name: "dialog-cancel"
            onTriggered: { app.closePopup(); dialog.close(); }
        }
    ]

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Controls.Label {
            Layout.fillWidth: true
            Layout.maximumWidth: Kirigami.Units.gridUnit * 24
            text: dialog.payload.message || ""
            wrapMode: Text.WordWrap
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: dialog.conflicts
            type: Kirigami.MessageType.Warning
            text: qsTr("Resolve the conflicts in your editor, then continue.")
        }

        ConflictList {
            Layout.fillWidth: true
            visible: dialog.conflicts
            files: app.conflicts.files
        }
    }
}
