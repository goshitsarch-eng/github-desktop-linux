// A path entry with a Choose… button.
//
// This is where the network-share fix surfaces: popups.chooseFolder() returns
// either a usable local path or an explanation, and an unusable pick shows an
// inline message with a way to mount the share — never a click that appears
// to do nothing.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: root

    property alias text: field.text
    property string dialogTitle: qsTr("Choose a folder")
    property string placeholder: ""

    spacing: Kirigami.Units.smallSpacing

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        Controls.TextField {
            id: field
            Layout.fillWidth: true
            placeholderText: root.placeholder
            onTextEdited: problem.visible = false
        }

        Controls.Button {
            text: qsTr("Choose…")
            icon.name: app.iconFor("folder-open")
            onClicked: {
                const picked = popups.chooseFolder(root.dialogTitle, field.text);
                if (picked.cancelled) {
                    return;
                }
                if (picked.path) {
                    field.text = picked.path;
                    problem.visible = false;
                    return;
                }
                problem.text = picked.help ? picked.error + " " + picked.help : picked.error;
                problem.unmountedUrl = picked.url || "";
                problem.visible = true;
            }
        }
    }

    Kirigami.InlineMessage {
        id: problem

        property string unmountedUrl: ""

        Layout.fillWidth: true
        visible: false
        type: Kirigami.MessageType.Warning
        actions: Kirigami.Action {
            visible: problem.unmountedUrl !== ""
            icon.name: app.iconFor("network-share")
            text: qsTr("Open in file manager")
            onTriggered: popups.openInFileManager(problem.unmountedUrl)
        }
    }
}
