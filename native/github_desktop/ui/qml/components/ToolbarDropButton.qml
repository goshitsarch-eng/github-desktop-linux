// Desktop's two-line toolbar buttons: a caption above the current value, with
// a dropdown indicator. Kirigami has no equivalent, so this is a plain
// ToolButton with a custom contentItem — everything else (hover, focus ring,
// pressed state) comes from the platform style.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Controls.ToolButton {
    id: control

    property string label: ""
    property string sublabel: ""
    property string iconName: ""

    Accessible.name: sublabel + ": " + label
    Controls.ToolTip.text: label
    Controls.ToolTip.visible: hovered && label !== ""
    Controls.ToolTip.delay: Kirigami.Units.toolTipDelay

    contentItem: RowLayout {
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Icon {
            source: control.iconName
            visible: control.iconName !== ""
            implicitWidth: Kirigami.Units.iconSizes.small
            implicitHeight: Kirigami.Units.iconSizes.small
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0

            Controls.Label {
                Layout.fillWidth: true
                text: control.sublabel
                elide: Text.ElideRight
                opacity: 0.7
                font: Kirigami.Theme.smallFont
                horizontalAlignment: Text.AlignLeft
            }

            Controls.Label {
                Layout.fillWidth: true
                text: control.label
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignLeft
            }
        }

        Kirigami.Icon {
            source: "arrow-down"
            implicitWidth: Kirigami.Units.iconSizes.small
            implicitHeight: Kirigami.Units.iconSizes.small
            opacity: control.enabled ? 0.8 : 0.4
        }
    }
}
