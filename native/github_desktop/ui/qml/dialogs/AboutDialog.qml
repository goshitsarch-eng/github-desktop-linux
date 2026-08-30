import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("About %1").arg(app.appName)
    standardButtons: Controls.Dialog.Close

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.largeSpacing

            Kirigami.Icon {
                source: app.iconFor("app")
                implicitWidth: Kirigami.Units.iconSizes.huge
                implicitHeight: Kirigami.Units.iconSizes.huge
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: Kirigami.Units.smallSpacing

                Kirigami.Heading { text: app.appName; level: 2 }
                Controls.Label { text: qsTr("Version %1").arg(app.version); opacity: 0.8 }
                Controls.Label {
                    Layout.fillWidth: true
                    Layout.maximumWidth: Kirigami.Units.gridUnit * 22
                    text: qsTr("An unofficial Linux port of GitHub Desktop, built with Qt 6 and Kirigami. Not affiliated with GitHub, Inc.")
                    wrapMode: Text.WordWrap
                    opacity: 0.8
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Controls.Button {
                text: qsTr("Release notes")
                onClicked: app.showPopup("ReleaseNotes", {})
            }
            Controls.Button {
                text: qsTr("Acknowledgements")
                onClicked: app.showPopup("Acknowledgements", {})
            }
            Item { Layout.fillWidth: true }
        }
    }
}
