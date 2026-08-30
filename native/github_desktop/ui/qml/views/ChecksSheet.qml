// Pull request checks. Statuses and the summary text come from
// github/ci_checks.py; this shows them and offers the two things Desktop
// offers: re-run what failed, and open a job's logs.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Kirigami.OverlaySheet {
    id: sheet

    parent: Controls.Overlay.overlay
    title: qsTr("Pull request checks")

    header: ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading { text: sheet.title }

        Controls.Label {
            Layout.fillWidth: true
            text: app.checks.summary
            wrapMode: Text.WordWrap
            opacity: 0.8
        }
    }

    footer: RowLayout {
        Controls.Button {
            text: qsTr("Re-run failed checks")
            icon.name: app.iconFor("fetch")
            enabled: app.checks.canRerun
            objectName: "job-rerun"
            onClicked: app.showPopup("CICheckRunRerun", {})
        }
        Item { Layout.fillWidth: true }
    }

    ColumnLayout {
        implicitWidth: Kirigami.Units.gridUnit * 26
        implicitHeight: Kirigami.Units.gridUnit * 20
        spacing: 0

        // Desktop `LoadingCheckRuns` / `loadingActionWorkflows`
        RowLayout {
            objectName: "loading-check-runs"
            Layout.fillWidth: true
            Layout.margins: Kirigami.Units.smallSpacing
            visible: app.checks.loading
            spacing: Kirigami.Units.smallSpacing

            Controls.BusyIndicator {
                running: app.checks.loading
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
            }

            Controls.Label { text: qsTr("Loading check runs…") }
        }

        ListView {
            id: runs
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: app.checkRuns
            clip: true

            Kirigami.PlaceholderMessage {
                anchors.centerIn: parent
                width: parent.width - Kirigami.Units.largeSpacing * 4
                visible: runs.count === 0 && !app.checks.loading
                icon.name: app.iconFor("checks-ok")
                text: qsTr("No checks reported for this branch")
            }

            // Desktop `CICheckRunStepListHeader`: the per-check step summary.
            header: Controls.ItemDelegate {
                objectName: "ci-check-run-steps-header"
                width: runs.width
                enabled: false
                visible: app.checks.stepSummary !== ""
                height: visible ? implicitHeight : 0
                contentItem: Controls.Label {
                    text: app.checks.stepSummary
                    opacity: 0.8
                    font: Kirigami.Theme.smallFont
                }
            }

            delegate: Controls.ItemDelegate {
                width: runs.width
                onClicked: app.openUrl(model.url)

                contentItem: RowLayout {
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Icon {
                        source: model.icon
                        implicitWidth: Kirigami.Units.iconSizes.small
                        implicitHeight: Kirigami.Units.iconSizes.small
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0

                        Controls.Label {
                            Layout.fillWidth: true
                            text: model.name
                            elide: Text.ElideRight
                        }

                        Controls.Label {
                            Layout.fillWidth: true
                            visible: model.description !== ""
                            text: model.description
                            elide: Text.ElideRight
                            opacity: 0.7
                            font: Kirigami.Theme.smallFont
                        }
                    }

                    Controls.ToolButton {
                        icon.name: app.iconFor("folder-open")
                        display: Controls.AbstractButton.IconOnly
                        Accessible.name: qsTr("Show logs in your File Manager")
                        Controls.ToolTip.text: Accessible.name
                        Controls.ToolTip.visible: hovered
                        onClicked: app.revealCheckLogs(model.checkId)
                    }

                    Controls.ToolButton {
                        objectName: "view-check-externally"
                        icon.name: app.iconFor("browser")
                        display: Controls.AbstractButton.IconOnly
                        Accessible.name: qsTr("View logs")
                        Controls.ToolTip.text: Accessible.name
                        Controls.ToolTip.visible: hovered
                        onClicked: app.openUrl(model.url)
                    }
                }
            }
        }
    }
}
