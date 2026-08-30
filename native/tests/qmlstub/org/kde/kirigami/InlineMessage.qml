import QtQuick
import QtQuick.Controls as Controls

Controls.Control {
    signal linkActivated(string link)

    property string text: ""
    property int type: 0
    property list<QtObject> actions
    property bool showCloseButton: false
    property string icon: ""
}
