import QtQuick
import QtQuick.Controls as Controls

// Enough of Kirigami's PageRow for the app to set an initial page and for
// tests to read back what is on the stack.
Controls.StackView {
    property var initialPage: null
    property QtObject globalToolBar: QtObject { property int style: 0 }

    onInitialPageChanged: {
        if (initialPage) {
            clear();
            push(initialPage);
        }
    }
}
