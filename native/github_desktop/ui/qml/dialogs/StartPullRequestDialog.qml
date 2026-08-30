import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Create pull request")
    preferredWidth: Kirigami.Units.gridUnit * 30
    values: ({
        "title": titleField.text,
        "body": bodyArea.text,
        "base": baseBox.currentText,
        "draft": draftBox.checked
    })

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Kirigami.FormLayout {
            Layout.fillWidth: true

            Controls.ComboBox {
                id: baseBox
                Kirigami.FormData.label: qsTr("Merge into:")
                model: dialog.payload.base_branches || []
            }

            Controls.TextField {
                id: titleField
                Kirigami.FormData.label: qsTr("Title:")
                text: dialog.payload.title || ""
            }
        }

        Controls.ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: Kirigami.Units.gridUnit * 8
            Controls.TextArea {
                id: bodyArea
                text: dialog.payload.body || ""
                wrapMode: TextEdit.Wrap
                placeholderText: qsTr("Describe the change")
            }
        }

        Controls.CheckBox {
            id: draftBox
            text: qsTr("Create as a draft")
        }
    }
}
