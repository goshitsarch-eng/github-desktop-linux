// Remote URL, ignored files and the per-repository git identity — the three
// groups Desktop puts in this dialog.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Repository settings")
    preferredWidth: Kirigami.Units.gridUnit * 32
    values: ({
        "remoteUrl": remoteField.text,
        "gitignore": ignoreArea.text,
        "authorName": nameField.text,
        "authorEmail": emailField.text
    })

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Controls.TabBar {
            id: tabs
            Layout.fillWidth: true
            Controls.TabButton { text: qsTr("Remote") }
            Controls.TabButton { text: qsTr("Ignored files") }
            Controls.TabButton { text: qsTr("Git config") }
        }

        StackLayout {
            Layout.fillWidth: true
            currentIndex: tabs.currentIndex

            Kirigami.FormLayout {
                Controls.TextField {
                    id: remoteField
                    Kirigami.FormData.label: qsTr("Primary remote (origin):")
                    text: dialog.payload.remote_url || ""
                }
            }

            Controls.ScrollView {
                implicitHeight: Kirigami.Units.gridUnit * 12
                Controls.TextArea {
                    id: ignoreArea
                    text: dialog.payload.gitignore || ""
                    font.family: "monospace"
                    wrapMode: TextEdit.NoWrap
                }
            }

            Kirigami.FormLayout {
                Controls.TextField {
                    id: nameField
                    Kirigami.FormData.label: qsTr("Name:")
                    text: dialog.payload.author_name || ""
                }
                Controls.TextField {
                    id: emailField
                    Kirigami.FormData.label: qsTr("Email:")
                    text: dialog.payload.author_email || ""
                }
            }
        }
    }
}
