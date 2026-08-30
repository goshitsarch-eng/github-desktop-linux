pragma Singleton
import QtQuick

// Breeze Light values; the real Theme reads the user's colour scheme.
QtObject {
    readonly property color backgroundColor: "#fcfcfc"
    readonly property color alternateBackgroundColor: "#eff0f1"
    readonly property color highlightColor: "#3daee9"
    readonly property color textColor: "#232629"
    readonly property color disabledTextColor: "#9a9a9a"
    readonly property color positiveTextColor: "#27ae60"
    readonly property color negativeTextColor: "#da4453"
    readonly property color neutralTextColor: "#f67400"
    readonly property color positiveBackgroundColor: "#e8f8ee"
    readonly property color negativeBackgroundColor: "#fbe9eb"
    readonly property font smallFont: Qt.font({ pointSize: 8 })
    readonly property font defaultFont: Qt.font({ pointSize: 10 })
}
