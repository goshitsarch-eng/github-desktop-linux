// Changed files plus the commit form, the way Desktop lays the Changes tab
// out: a filterable checkable list on top, the message and Commit button
// pinned to the bottom.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: root
    spacing: 0

    RowLayout {
        Layout.fillWidth: true
        Layout.margins: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing

        Controls.CheckBox {
            id: includeAll
            Accessible.name: qsTr("Include all changes in the commit")
            checkState: {
                if (app.changedFiles.count === 0) return Qt.Unchecked;
                let checked = 0;
                let partial = false;
                for (let i = 0; i < app.changedFiles.count; ++i) {
                    const row = app.changedFiles.get(i);
                    if (row.included === 1) checked += 1;
                    else if (row.included === 2) partial = true;
                }
                if (partial || (checked > 0 && checked < app.changedFiles.count)) return Qt.PartiallyChecked;
                return checked === 0 ? Qt.Unchecked : Qt.Checked;
            }
            onClicked: app.setAllIncluded(checkState !== Qt.Checked)
        }

        Kirigami.SearchField {
            id: changesFilter
            Layout.fillWidth: true
            visible: app.settings.showChangesFilter
            placeholderText: qsTr("Filter changed files")
            // Desktop `onIncludeAllChanged` keeps the header checkbox in step;
            // filtering only narrows what the list shows.
            onTextChanged: app.setChangesFilter(text)
        }

        Controls.ToolButton {
            icon.name: app.iconFor("search")
            checkable: true
            checked: app.settings.showChangesFilter
            Accessible.name: checked ? qsTr("Hide changes filter") : qsTr("Filter Options")
            Controls.ToolTip.text: Accessible.name
            Controls.ToolTip.visible: hovered
            onClicked: app.updateSetting("show_changes_filter", checked)
        }

        Controls.ToolButton {
            icon.name: app.iconFor("stash")
            visible: app.stashes.count > 0
            checkable: true
            Accessible.name: qsTr("Stashed Changes")
            Controls.ToolTip.text: qsTr("View stash")
            Controls.ToolTip.visible: hovered
            onClicked: app.toggleStash()
        }
    }

    // Desktop `renderHiddenChangesWarning`: filters can hide a file that is
    // still staged, so say so before the commit surprises anyone.
    Kirigami.InlineMessage {
        id: hiddenChangesWarning
        objectName: "hidden-changes-warning"
        Layout.fillWidth: true
        Layout.margins: visible ? Kirigami.Units.smallSpacing : 0
        visible: app.changesFilter.hiddenCount > 0
        type: Kirigami.MessageType.Information
        text: app.changesFilter.hiddenWarning
        Controls.ToolTip.text: app.changesFilter.hiddenLabel
        actions: Kirigami.Action {
            text: qsTr("Clear filters")
            onTriggered: { changesFilter.text = ""; app.clearChangesFilters(); }
        }
    }

    Kirigami.Separator { Layout.fillWidth: true }

    Controls.ScrollView {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff

        ListView {
            id: fileList
            model: app.changedFiles
            clip: true
            currentIndex: -1

            Kirigami.PlaceholderMessage {
                anchors.centerIn: parent
                width: parent.width - Kirigami.Units.largeSpacing * 4
                visible: fileList.count === 0
                icon.name: app.changesFilter.filtering
                    ? app.iconFor("search")
                    : app.iconFor("checks-ok")
                text: app.changesFilter.filtering
                    ? qsTr("No files match your current filters")
                    : qsTr("No local changes")
                explanation: app.changesFilter.filtering
                    ? ""
                    : qsTr("There is nothing to commit right now.")
                helpfulAction: app.changesFilter.filtering ? clearFiltersAction : null

                Kirigami.Action {
                    id: clearFiltersAction
                    text: qsTr("Clear filters")
                    icon.name: app.iconFor("close")
                    onTriggered: { changesFilter.text = ""; app.clearChangesFilters(); }
                }
            }

            delegate: ChangedFileDelegate {
                width: fileList.width
                onOpened: app.selectFile(model.path)
                onInclusionToggled: app.setFileIncluded(model.path, model.included !== 1)
                // Desktop `onDoubleClick` opens the file in the external editor.
                onOpenRequested: app.openPath(model.path)
                onContextMenuRequested: fileMenu.popupFor(model)
            }
        }
    }

    Kirigami.Separator { Layout.fillWidth: true }

    CommitForm { Layout.fillWidth: true }

    ChangedFileMenu { id: fileMenu }
}
