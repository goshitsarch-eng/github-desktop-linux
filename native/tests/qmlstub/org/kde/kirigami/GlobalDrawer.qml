import QtQuick
import QtQuick.Controls as Controls

Controls.Drawer {
    property string title: ""
    property string titleIcon: ""
    property bool isMenu: false
    property list<QtObject> actions
    property list<QtObject> topContent
}
