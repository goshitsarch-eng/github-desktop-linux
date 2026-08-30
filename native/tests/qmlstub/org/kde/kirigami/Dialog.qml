import QtQuick
import QtQuick.Controls as Controls

Controls.Dialog {
    property int preferredWidth: 0
    property int preferredHeight: 0
    property bool showCloseButton: true
    property bool flatFooterButtons: true
    property list<QtObject> customFooterActions
    property Item mainItem: null
}
