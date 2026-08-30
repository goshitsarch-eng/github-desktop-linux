// A spinner with a label, used wherever Desktop shows an inline "loading…".

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

RowLayout {
    id: root

    objectName: "loading-indicator"

    property string text: ""
    property bool running: true

    visible: running
    spacing: Kirigami.Units.smallSpacing

    Controls.BusyIndicator {
        running: root.running
        implicitWidth: Kirigami.Units.iconSizes.small
        implicitHeight: Kirigami.Units.iconSizes.small
    }

    Controls.Label {
        Layout.fillWidth: true
        text: root.text
        elide: Text.ElideRight
        opacity: 0.8
    }
}
