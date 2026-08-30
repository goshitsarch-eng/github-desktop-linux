// Desktop lets the two toolbar dropdowns be resized, and announces the new
// width for screen readers. The limits come from the store
// (`update_resizable_constraints`) so they track the window width.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Item {
    id: root

    /// "branch" or "push"; picks which constraints and stored width to use.
    property string kind: "branch"
    property string description: ""
    default property alias content: holder.data

    readonly property var limits: app.resizableLimits(kind)

    implicitWidth: Math.max(limits.min, Math.min(limits.max, limits.width))
    implicitHeight: holder.implicitHeight

    Accessible.name: description
    Accessible.role: Accessible.Separator

    Item {
        id: holder
        anchors.fill: parent
    }

    // Drag the trailing edge.
    Item {
        width: Kirigami.Units.smallSpacing
        height: parent.height
        anchors.right: parent.right

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.SizeHorCursor
            property real startX: 0
            property real startWidth: 0

            onPressed: mouse => {
                startX = mouse.x;
                startWidth = root.width;
                app.setResizeActive(root.kind, true);
            }
            onPositionChanged: mouse => {
                if (!pressed) {
                    return;
                }
                app.setResizableWidth(root.kind, startWidth + (mouse.x - startX));
            }
            onReleased: app.setResizeActive(root.kind, false)
            onDoubleClicked: app.resetResizableWidth(root.kind)
        }
    }

    // Desktop binds Ctrl+9 / Ctrl+8 to the focused resizable.
    Shortcut {
        sequences: ["Ctrl+9"]
        enabled: app.activeResizable === root.kind
        onActivated: root.nudge(1)
    }
    Shortcut {
        sequences: ["Ctrl+8"]
        enabled: app.activeResizable === root.kind
        onActivated: root.nudge(-1)
    }

    function nudge(direction) {
        const announcement = app.nudgeResizable(root.kind, direction);
        if (announcement) {
            app.announce(announcement);
        }
    }
}
