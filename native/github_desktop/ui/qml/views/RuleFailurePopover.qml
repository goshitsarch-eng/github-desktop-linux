// Repository rules that would block this commit or push. Desktop shows them
// in a popover off the commit warning; the failure list itself comes from
// github/repo_rules.py.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Controls.Popup {
    id: popover

    width: Kirigami.Units.gridUnit * 22
    padding: Kirigami.Units.largeSpacing
    closePolicy: Controls.Popup.CloseOnEscape | Controls.Popup.CloseOnPressOutside

    readonly property var failures: app.repoRules

    ColumnLayout {
        anchors.fill: parent
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading {
            Layout.fillWidth: true
            level: 4
            text: popover.failures.title
        }

        Repeater {
            model: popover.failures.rules
            delegate: Controls.Label {
                Layout.fillWidth: true
                text: "• " + modelData
                wrapMode: Text.WordWrap
            }
        }

        Controls.Button {
            Layout.alignment: Qt.AlignRight
            text: qsTr("View repository rulesets")
            icon.name: app.iconFor("browser")
            visible: popover.failures.rulesetsUrl !== ""
            onClicked: app.openUrl(popover.failures.rulesetsUrl)
        }
    }
}
