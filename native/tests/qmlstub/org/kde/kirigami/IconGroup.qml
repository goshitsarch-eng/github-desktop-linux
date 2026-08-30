import QtQuick

// Stand-in for the QQuickIcon grouped property Kirigami exposes as `icon`.
QtObject {
    property string name: ""
    property string source: ""
    property color color: "transparent"
    property int width: 16
    property int height: 16
}
