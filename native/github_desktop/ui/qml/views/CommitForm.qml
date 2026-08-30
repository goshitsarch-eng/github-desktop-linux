// The commit message form. Summary, description, optional co-authors, and the
// "Commit to <branch>" button — the same shape and the same enablement rules
// as Desktop, computed in bridge.commitForm.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami
import components

ColumnLayout {
    id: root

    readonly property var form: app.commitForm
    /// Desktop `showInputLabels`: label the fields rather than relying on
    /// placeholder text, which disappears as soon as you type.
    property bool showInputLabels: true
    visible: form.visible
    spacing: Kirigami.Units.smallSpacing

    function push() {
        app.setCommitMessage(summaryField.text, descriptionField.text);
    }

    Connections {
        target: app
        // Only overwrite the fields when the store's copy actually differs,
        // so a refresh mid-typing never moves the cursor.
        function onChanged() {
            if (summaryField.text !== root.form.summary && !summaryField.activeFocus) {
                summaryField.text = root.form.summary;
            }
            if (descriptionField.text !== root.form.description && !descriptionField.activeFocus) {
                descriptionField.text = root.form.description;
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.smallSpacing
        Layout.rightMargin: Kirigami.Units.smallSpacing
        Layout.topMargin: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing

        // Desktop `renderAvatar`: initials when there is no gravatar to show,
        // and a toggle-tip (`isToggleTip`) with the identity behind it.
        Kirigami.Avatar {
            id: authorAvatar
            implicitWidth: Kirigami.Units.iconSizes.medium
            implicitHeight: Kirigami.Units.iconSizes.medium
            name: root.form.authorName
            source: root.form.avatarUrl
            Accessible.name: qsTr("Committing as %1").arg(root.form.authorName)

            TapHandler {
                onTapped: identityTip.opened ? identityTip.close() : identityTip.open()
            }

            Controls.Popup {
                id: identityTip
                y: authorAvatar.height
                padding: Kirigami.Units.largeSpacing
                Controls.Label {
                    text: qsTr("Committing as %1 <%2>")
                        .arg(root.form.authorName).arg(root.form.authorEmail)
                }
            }
        }

        Controls.Label {
            visible: root.showInputLabels
            text: qsTr("Summary")
            font: Kirigami.Theme.smallFont
            opacity: 0.75
        }

        AutocompleteField {
            id: summaryField
            Layout.fillWidth: true
            placeholderText: qsTr("Summary (required)")
            text: root.form.summary
            spellcheck: root.form.spellcheck
            onTextEdited: root.push()
            onAccepted: descriptionField.forceActiveFocus()
        }

        // Desktop's "Completeness indicator": fills as the summary reaches the
        // ideal length, rather than scolding once it is past it.
        Controls.ProgressBar {
            Layout.preferredWidth: Kirigami.Units.gridUnit * 2
            visible: app.settings.showCommitLengthWarning
            from: 0
            to: 1
            value: root.form.completeness
            Accessible.name: qsTr("Completeness indicator")
        }

        Controls.ToolButton {
            id: generateButton
            visible: root.form.canGenerate || root.form.isGenerating
            enabled: root.form.canGenerate
            icon.name: app.iconFor("lightbulb")
            display: Controls.AbstractButton.IconOnly
            Accessible.name: root.form.generateLabel
            // Desktop `onGenerateCommitMessage`
            Controls.ToolTip.text: enabled ? root.form.generateLabel : root.form.generateDisabledReason
            Controls.ToolTip.visible: hovered
            onClicked: app.generateCommitMessage()
        }
    }

    Controls.Label {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.smallSpacing
        visible: root.form.isGenerating
        text: root.form.generatingLabel
        font: Kirigami.Theme.smallFont
        opacity: 0.8
    }

    Controls.Label {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.smallSpacing
        Layout.rightMargin: Kirigami.Units.smallSpacing
        visible: root.form.lengthHint !== ""
        text: root.form.lengthHint
        wrapMode: Text.WordWrap
        font: Kirigami.Theme.smallFont
        opacity: 0.8
    }

    Controls.ScrollView {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.smallSpacing
        Layout.rightMargin: Kirigami.Units.smallSpacing
        Layout.preferredHeight: Kirigami.Units.gridUnit * 5

        Controls.TextArea {
            id: descriptionField
            placeholderText: qsTr("Description")
            text: root.form.description
            wrapMode: TextEdit.Wrap
            onTextChanged: root.push()
        }
    }

    Repeater {
        model: root.form.warnings
        delegate: Kirigami.InlineMessage {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.smallSpacing
            Layout.rightMargin: Kirigami.Units.smallSpacing
            visible: true
            type: Kirigami.MessageType.Warning
            text: modelData.markup
            onLinkActivated: link => app.openUrl(link)

            actions: Kirigami.Action {
                visible: app.repoRules.rules.length > 0
                text: qsTr("Details")
                // Desktop `toggleRuleFailurePopover` / `isRuleFailurePopoverOpen`
                onTriggered: ruleFailures.opened ? ruleFailures.close() : ruleFailures.open()
            }
        }
    }

    RuleFailurePopover { id: ruleFailures }

    Controls.CheckBox {
        id: coAuthorBox
        Layout.leftMargin: Kirigami.Units.smallSpacing
        visible: root.form.coAuthorsAvailable
        checked: root.form.showCoAuthors
        text: qsTr("Add co-authors")
        // Desktop `onToggleCoAuthors`
        onToggled: app.setShowCoAuthors(checked)
    }

    Repeater {
        model: root.form.showCoAuthors ? app.coAuthors : null
        delegate: Controls.Label {
            Layout.fillWidth: true
            Layout.leftMargin: Kirigami.Units.gridUnit
            text: model.username ? "@" + model.username : model.name
            font: Kirigami.Theme.smallFont
            opacity: 0.8
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.margins: Kirigami.Units.smallSpacing
        spacing: Kirigami.Units.smallSpacing

        Controls.Button {
            Layout.fillWidth: true
            text: root.form.buttonLabel
            icon.name: app.iconFor("commit")
            enabled: root.form.canCommit
            onClicked: app.commit()
        }

        Controls.BusyIndicator {
            running: root.form.isCommitting || root.form.isGenerating
            visible: running
            implicitWidth: Kirigami.Units.iconSizes.small
            implicitHeight: Kirigami.Units.iconSizes.small
        }

        Controls.ToolButton {
            visible: root.form.amending
            icon.name: app.iconFor("close")
            text: qsTr("Stop amending")
            display: Controls.AbstractButton.IconOnly
            onClicked: app.stopAmending()
        }
    }
}
