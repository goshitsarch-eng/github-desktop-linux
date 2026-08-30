// The tutorial side panel. Steps and their "should I nudge?" rules come from
// ui/tutorial.py; this renders them and the nudge arrows that point at the
// control the current step is about.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import components

ColumnLayout {
    id: root

    readonly property var tutorial: app.tutorial
    visible: tutorial.active
    spacing: Kirigami.Units.smallSpacing

    Kirigami.Heading {
        Layout.fillWidth: true
        Layout.margins: Kirigami.Units.smallSpacing
        level: 3
        text: root.tutorial.done ? qsTr("You're done!") : qsTr("Let's get started!")
    }

    Controls.Label {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.smallSpacing
        Layout.rightMargin: Kirigami.Units.smallSpacing
        text: root.tutorial.summary
        wrapMode: Text.WordWrap
        opacity: 0.85
    }

    Repeater {
        model: root.tutorial.steps
        delegate: RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.smallSpacing
            Layout.rightMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing

            Kirigami.Icon {
                source: modelData.complete ? app.iconFor("checks-ok") : app.iconFor("tutorial")
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
                opacity: modelData.current ? 1.0 : 0.6
            }

            Controls.Label {
                Layout.fillWidth: true
                text: modelData.title
                wrapMode: Text.WordWrap
                font.bold: modelData.current
                opacity: modelData.complete ? 0.6 : 1.0
            }

            // Desktop's nudge arrow points at the control the step is about.
            NudgeArrow {
                visible: modelData.nudge
                state: modelData.nudgeState
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.margins: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing

        Controls.Button {
            visible: root.tutorial.done
            text: qsTr("Explore projects on GitHub")
            icon.name: app.iconFor("browser")
            onClicked: app.exploreGitHub()
        }

        Item { Layout.fillWidth: true }

        Controls.Button {
            text: qsTr("Exit tutorial")
            flat: true
            onClicked: app.showPopup("ConfirmExitTutorial", {})
        }
    }
}
