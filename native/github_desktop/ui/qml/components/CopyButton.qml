// Desktop's copy-button: copies on click and confirms for a moment.
// The labels live in ui/copy_button.py so they stay checkable.

import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Controls.ToolButton {
    id: control

    objectName: "copy-button"

    property string copyContent: ""
    property string ariaLabel: app.copyShaLabel
    property bool showCopied: false
    /// Desktop `openTooltipOnClick`: the confirmation replaces the tooltip.
    property bool openTooltipOnClick: true

    icon.name: showCopied ? app.iconFor("checks-ok") : app.iconFor("copy")
    display: Controls.AbstractButton.IconOnly
    Accessible.name: ariaLabel
    Controls.ToolTip.text: showCopied ? qsTr("Copied!") : ariaLabel
    Controls.ToolTip.visible: hovered || (openTooltipOnClick && showCopied)
    Controls.ToolTip.delay: showCopied ? 0 : Kirigami.Units.toolTipDelay

    onClicked: {
        app.copyToClipboard(control.copyContent);
        control.showCopied = true;
        copiedTimer.restart();
    }

    Timer {
        id: copiedTimer
        interval: 2000
        onTriggered: control.showCopied = false
    }
}
