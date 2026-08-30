// Settings. Kirigami's FormLayout inside a tabbed dialog is the shape KDE
// apps use for a settings window with a handful of categories.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

BaseDialog {
    id: dialog

    title: qsTr("Settings")
    preferredWidth: Kirigami.Units.gridUnit * 32
    standardButtons: Controls.Dialog.Close
    handled: true   // each control saves as it changes

    ColumnLayout {
        spacing: Kirigami.Units.smallSpacing

        Controls.TabBar {
            id: tabs
            Layout.fillWidth: true
            Controls.TabButton { text: qsTr("Appearance"); icon.name: app.iconFor("appearance") }
            Controls.TabButton { text: qsTr("Git"); icon.name: app.iconFor("git") }
            Controls.TabButton { text: qsTr("Integrations"); icon.name: app.iconFor("integrations") }
            Controls.TabButton { text: qsTr("Notifications"); icon.name: app.iconFor("notifications") }
            Controls.TabButton { text: qsTr("Advanced"); icon.name: app.iconFor("advanced") }
        }

        StackLayout {
            Layout.fillWidth: true
            currentIndex: tabs.currentIndex

            Kirigami.FormLayout {
                Controls.ComboBox {
                    Kirigami.FormData.label: qsTr("Appearance:")
                    model: [qsTr("System"), qsTr("Light"), qsTr("Dark")]
                    currentIndex: theming.current === "light" ? 1 : theming.current === "dark" ? 2 : 0
                    onActivated: theming.setTheme(["system", "light", "dark"][currentIndex])
                }

                Controls.Label {
                    Kirigami.FormData.label: ""
                    text: theming.followsSystem
                        ? qsTr("Following the desktop colour scheme.")
                        : qsTr("Overriding the desktop colour scheme for this app.")
                    opacity: 0.8
                    font: Kirigami.Theme.smallFont
                }

                Controls.SpinBox {
                    Kirigami.FormData.label: qsTr("Tab size:")
                    from: 1
                    to: 16
                    value: app.settings.tabSize
                    onValueModified: app.updateSetting("tab_size", value)
                }

                Controls.CheckBox {
                    Kirigami.FormData.label: qsTr("Diffs:")
                    text: qsTr("Show side by side")
                    checked: app.settings.showSideBySideDiff
                    onToggled: app.updateSetting("show_side_by_side_diff", checked)
                }

                Controls.CheckBox {
                    text: qsTr("Hide whitespace changes")
                    checked: app.settings.hideWhitespaceInDiffs
                    onToggled: app.updateSetting("hide_whitespace_in_diffs", checked)
                }

                Controls.CheckBox {
                    text: qsTr("Show check marks for selectable lines")
                    checked: app.settings.showDiffCheckMarks
                    onToggled: app.updateSetting("show_diff_check_marks", checked)
                }

                Controls.CheckBox {
                    Kirigami.FormData.label: qsTr("Links:")
                    text: qsTr("Underline links")
                    checked: app.settings.underlineLinks
                    onToggled: app.updateSetting("underline_links", checked)
                }
            }

            // Git identity and the per-repository override Desktop offers.
            Kirigami.FormLayout {
                Controls.Label {
                    Kirigami.FormData.label: qsTr("For this repository I wish to")
                    text: app.gitConfig.scopeSummary
                    wrapMode: Text.WordWrap
                    opacity: 0.85
                }

                Controls.RadioButton {
                    text: qsTr("Use my global Git config")
                    checked: !app.gitConfig.isGitConfigLocal
                    onToggled: if (checked) app.setGitConfigLocal(false)
                }

                Controls.RadioButton {
                    text: qsTr("Use a local Git config")
                    checked: app.gitConfig.isGitConfigLocal
                    onToggled: if (checked) app.setGitConfigLocal(true)
                }

                Controls.TextField {
                    Kirigami.FormData.label: qsTr("Name:")
                    text: app.gitConfig.name
                    onEditingFinished: app.setGitIdentity(text, emailField.text)
                }

                Controls.TextField {
                    id: emailField
                    Kirigami.FormData.label: qsTr("Email:")
                    text: app.gitConfig.email
                    onEditingFinished: app.setGitIdentity(app.gitConfig.name, text)
                }

                Kirigami.InlineMessage {
                    Kirigami.FormData.label: ""
                    Layout.fillWidth: true
                    visible: app.gitConfig.emailMismatch
                    type: Kirigami.MessageType.Warning
                    text: qsTr("This email address doesn't match your GitHub account")
                }

                Controls.Button {
                    Kirigami.FormData.label: ""
                    text: qsTr("Edit global Git config")
                    onClicked: app.openGlobalGitConfig()
                }

                Controls.ComboBox {
                    Kirigami.FormData.label: qsTr("Line endings and whitespace:")
                    model: [qsTr("Use the platform default"), qsTr("Check out as-is, commit as-is")]
                    currentIndex: app.gitConfig.lineEndings
                    onActivated: app.setLineEndings(currentIndex)
                }

                Controls.CheckBox {
                    Kirigami.FormData.label: qsTr("Commit message:")
                    text: qsTr("Show commit length warning")
                    checked: app.settings.showCommitLengthWarning
                    onToggled: app.updateSetting("show_commit_length_warning", checked)
                }

                Controls.CheckBox {
                    // Desktop `onCommitSpellcheckEnabledChanged`
                    text: qsTr("Check spelling")
                    checked: app.settings.spellcheckEnabled
                    onToggled: app.updateSetting("spellcheck_enabled", checked)
                }

                Controls.CheckBox {
                    Kirigami.FormData.label: qsTr("Changed files:")
                    text: qsTr("Show the filter box")
                    checked: app.settings.showChangesFilter
                    onToggled: app.updateSetting("show_changes_filter", checked)
                }
            }

            // Desktop `openIntegrationPreferences`: editor and shell.
            Kirigami.FormLayout {
                Controls.ComboBox {
                    Kirigami.FormData.label: qsTr("External editor:")
                    model: app.integrations.editors
                    currentIndex: app.integrations.editorIndex
                    onActivated: app.setEditor(currentText)
                }

                Controls.Button {
                    Kirigami.FormData.label: ""
                    visible: app.integrations.editors.length === 0
                    text: qsTr("Download %1").arg(app.integrations.suggestedEditor)
                    onClicked: app.openUrl(app.integrations.suggestedEditorUrl)
                }

                Controls.CheckBox {
                    id: customEditorBox
                    Kirigami.FormData.label: qsTr("Custom editor:")
                    text: qsTr("Configure custom editor")
                    checked: app.integrations.useCustomEditor
                    onToggled: app.updateSetting("use_custom_editor", checked)
                }

                Controls.TextField {
                    Kirigami.FormData.label: qsTr("Command:")
                    visible: customEditorBox.checked
                    text: app.integrations.customEditorPath
                    onEditingFinished: app.updateSetting("custom_editor_path", text)
                }

                Controls.ComboBox {
                    Kirigami.FormData.label: qsTr("Shell:")
                    model: app.integrations.shells
                    currentIndex: app.integrations.shellIndex
                    onActivated: app.setShell(currentText)
                }
            }

            // Notifications and the stash button's toolbar behaviour.
            Kirigami.FormLayout {
                Controls.CheckBox {
                    Kirigami.FormData.label: qsTr("Notifications:")
                    text: qsTr("Show desktop notifications")
                    checked: app.settings.notificationsEnabled
                    onToggled: app.updateSetting("notifications_enabled", checked)
                }

                Controls.Label {
                    Kirigami.FormData.label: ""
                    text: qsTr("Notifications are only shown for high-signal events.")
                    wrapMode: Text.WordWrap
                    opacity: 0.8
                    font: Kirigami.Theme.smallFont
                }

                Controls.RadioButton {
                    Kirigami.FormData.label: qsTr("Show the stash button:")
                    text: qsTr("Always available in the toolbar")
                    checked: !app.settings.stashButtonWhenExists
                    onToggled: if (checked) app.updateSetting("stash_button_when_exists", false)
                }

                Controls.RadioButton {
                    text: qsTr("When a stash exists")
                    checked: app.settings.stashButtonWhenExists
                    onToggled: if (checked) app.updateSetting("stash_button_when_exists", true)
                }
            }

            Kirigami.FormLayout {
                Controls.CheckBox {
                    Kirigami.FormData.label: qsTr("Confirm before:")
                    text: qsTr("Removing a repository")
                    checked: app.settings.confirmRepositoryRemoval
                    onToggled: app.updateSetting("confirm_repository_removal", checked)
                }

                Controls.CheckBox {
                    text: qsTr("Discarding changes")
                    checked: app.settings.confirmDiscardChanges
                    onToggled: app.updateSetting("confirm_discard_changes", checked)
                }

                Controls.CheckBox {
                    text: qsTr("Force pushing")
                    checked: app.settings.confirmForcePush
                    onToggled: app.updateSetting("confirm_force_push", checked)
                }

                Controls.CheckBox {
                    Kirigami.FormData.label: qsTr("Credentials:")
                    text: qsTr("Use Git Credential Manager")
                    checked: app.settings.useExternalCredentialHelper
                    onToggled: app.updateSetting("use_external_credential_helper", checked)
                }

                Controls.Label {
                    Kirigami.FormData.label: ""
                    text: "<a href=\"https://gh.io/gcm\">" + qsTr("Learn more") + "</a>"
                    textFormat: Text.RichText
                    onLinkActivated: link => app.openUrl(link)
                    font: Kirigami.Theme.smallFont
                }

                Controls.CheckBox {
                    Kirigami.FormData.label: qsTr("Usage:")
                    text: qsTr("Help GitHub Desktop improve by submitting usage stats")
                    checked: !app.settings.optOutOfUsageTracking
                    onToggled: app.updateSetting("opt_out_of_usage_tracking", !checked)
                }

                Controls.Label {
                    Kirigami.FormData.label: ""
                    text: "<a href=\"https://desktop.github.com/usage-data/\">"
                        + qsTr("Learn more about user metrics.") + "</a>"
                    textFormat: Text.RichText
                    onLinkActivated: link => app.openUrl(link)
                    font: Kirigami.Theme.smallFont
                }

                Controls.Button {
                    Kirigami.FormData.label: ""
                    text: qsTr("Show User Guides")
                    onClicked: app.openUrl("https://docs.github.com/en/desktop")
                }
            }
        }
    }
}
