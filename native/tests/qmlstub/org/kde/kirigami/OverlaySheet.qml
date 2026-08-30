import QtQuick
import QtQuick.Controls as Controls

// Controls.Dialog already provides title, header, footer and a default
// content property, which is everything the app uses an OverlaySheet for.
Controls.Dialog {
    property bool showCloseButton: true
}
