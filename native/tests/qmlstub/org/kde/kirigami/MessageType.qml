// Kirigami's MessageType enum. A QML `enum` block gives `MessageType.Warning`
// the same way the C++ enum does.
import QtQuick

QtObject {
    enum Type {
        Information,
        Positive,
        Warning,
        Error
    }
}
