import QtQuick
import QtQuick.Controls as Controls

Controls.ApplicationWindow {
    id: window

    property var globalDrawer: null
    property var contextDrawer: null
    property bool wideScreen: width > 60 * 18
    readonly property alias pageStack: stackRow

    function showPassiveNotification(message, timeout, actionText, callback) {}

    PageRow {
        id: stackRow
        anchors.fill: parent
    }
}
