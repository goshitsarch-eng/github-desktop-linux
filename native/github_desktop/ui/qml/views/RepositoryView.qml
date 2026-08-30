// The repository workspace: sidebar on the left, diff on the right.
//
// A SplitView rather than a Kirigami PageRow, because the two panes are read
// together rather than navigated between. The handle position is persisted
// through the store, matching what Desktop remembers.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Item {
    id: root

    Loader {
        anchors.fill: parent
        sourceComponent: {
            switch (app.repositoryState) {
            case "cloning": return cloningView;
            case "missing": return missingView;
            case "none": return noSelectionView;
            default: return workspace;
            }
        }
    }

    Component {
        id: workspace

        Controls.SplitView {
            orientation: Qt.Horizontal

            onResizingChanged: {
                if (!resizing && sidebar.width > 0) {
                    app.saveSidebarWidth(Math.round(sidebar.width));
                }
            }

            ColumnLayout {
                id: sidebar

                Controls.SplitView.preferredWidth: app.settings.sidebarWidth
                Controls.SplitView.minimumWidth: Kirigami.Units.gridUnit * 14
                Controls.SplitView.maximumWidth: Kirigami.Units.gridUnit * 34
                spacing: 0

                Controls.TabBar {
                    id: sectionTabs
                    Layout.fillWidth: true
                    currentIndex: app.section === "history" ? 1 : 0

                    Controls.TabButton {
                        text: app.changedFileCount > 0
                            ? qsTr("Changes (%1)").arg(app.changedFileCount)
                            : qsTr("Changes")
                        icon.name: app.iconFor("changes")
                        onClicked: app.setSection("changes")
                    }
                    Controls.TabButton {
                        text: qsTr("History")
                        icon.name: app.iconFor("history")
                        onClicked: app.setSection("history")
                    }
                }

                Kirigami.Separator { Layout.fillWidth: true }

                Loader {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    sourceComponent: {
                        if (app.stashVisible) return stashViewer;
                        return app.section === "history" ? historySidebar : changesSidebar;
                    }
                }
            }

            DiffPane {
                Controls.SplitView.fillWidth: true
                Controls.SplitView.minimumWidth: Kirigami.Units.gridUnit * 20
            }

            TutorialPanel {
                Controls.SplitView.preferredWidth: Kirigami.Units.gridUnit * 16
                Controls.SplitView.minimumWidth: Kirigami.Units.gridUnit * 12
                visible: app.tutorial.active
            }
        }
    }

    Component { id: changesSidebar; ChangesSidebar {} }
    Component { id: historySidebar; HistorySidebar {} }
    Component { id: stashViewer; StashViewer {} }

    Component {
        id: cloningView

        Kirigami.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 4
            icon.name: app.iconFor("clone")
            objectName: "CloningRepositoryView"
            text: qsTr("Cloning…")
            explanation: app.pushPull.description

            Controls.ProgressBar {
                Layout.fillWidth: true
                indeterminate: app.pushPull.progress <= 0
                value: app.pushPull.progress
            }

            Controls.Button {
                Layout.alignment: Qt.AlignHCenter
                text: qsTr("Cancel clone")
                onClicked: app.cancelClone()
            }
        }
    }

    Component {
        id: missingView

        Kirigami.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 4
            icon.name: app.iconFor("warning")
            text: qsTr("Can't find this repository")
            // The store's own wording when a CLI/protocol lookup misses is
            // "Sorry, I can't find that repository"; here we already know
            // which one it is, so name its last known location instead.
            explanation: qsTr("It was last seen at %1.").arg(app.repositoryPath)

            helpfulAction: Kirigami.Action {
                icon.name: app.iconFor("folder-open")
                text: qsTr("Locate…")
                onTriggered: {
                    const picked = popups.chooseFolder(qsTr("Locate repository"), app.repositoryPath);
                    if (picked.cancelled) {
                        return;
                    }
                    if (picked.path) {
                        app.relocateRepository(picked.path);
                    } else {
                        app.showError(picked.help ? picked.error + "\n\n" + picked.help : picked.error);
                    }
                }
            }
        }
    }

    Component {
        id: noSelectionView

        Kirigami.PlaceholderMessage {
            anchors.centerIn: parent
            width: parent.width - Kirigami.Units.gridUnit * 4
            icon.name: app.iconFor("repository")
            text: qsTr("No repository selected")
            explanation: qsTr("Choose a repository to see its changes and history.")

            helpfulAction: Kirigami.Action {
                icon.name: app.iconFor("repository")
                text: qsTr("Choose a repository")
                onTriggered: app.showPopup("AddRepository", {})
            }
        }
    }
}
