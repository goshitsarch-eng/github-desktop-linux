// The pulsing pointer the tutorial uses to draw the eye to a control.
// nudge_arrow_frame() in ui/tutorial.py owns the keyframes so the timing
// matches Desktop's `pointup` / `pointleft` animation.

import QtQuick
import org.kde.kirigami as Kirigami

Kirigami.Icon {
    id: arrow

    property string direction: "up"

    source: direction === "left" ? "arrow-right" : "arrow-down"
    implicitWidth: Kirigami.Units.iconSizes.small
    implicitHeight: Kirigami.Units.iconSizes.small

    states: [
        State { name: "nudge-arrow"; PropertyChanges { arrow.opacity: 0 } },
        State { name: "nudge-arrow-up"; PropertyChanges { arrow.opacity: 1 } },
        State { name: "nudge-arrow-left"; PropertyChanges { arrow.opacity: 1 } }
    ]

    SequentialAnimation on y {
        running: arrow.state !== "nudge-arrow"
        loops: Animation.Infinite
        NumberAnimation { to: -Kirigami.Units.smallSpacing; duration: Kirigami.Units.longDuration }
        NumberAnimation { to: 0; duration: Kirigami.Units.longDuration }
        PauseAnimation { duration: Kirigami.Units.longDuration * 4 }
    }
}
