// Turns a popup raised by the store into a Kirigami dialog.
//
// popups.dialogFor() names the QML file for a PopupType; this loads it,
// hands it the payload, and closes the store's popup when it is dismissed.
// Nesting is real — Desktop can raise an error on top of a dialog — so this
// keeps a stack rather than a single current dialog.

import QtQuick
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Item {
    id: host

    property var stack: []

    function openPopup(type, payload) {
        const name = popups.dialogFor(type);
        const component = Qt.createComponent(Qt.resolvedUrl("dialogs/" + name + ".qml"));
        if (component.status === Component.Error) {
            console.warn("dialog", name, "failed to load:", component.errorString());
            return;
        }
        const dialog = component.createObject(Controls.Overlay.overlay, {
            popupKind: type,
            payload: payload || ({})
        });
        if (!dialog) {
            console.warn("dialog", name, "could not be created");
            return;
        }
        host.stack.push(dialog);
        app.setModalOpen(true);
        dialog.closed.connect(function () {
            host.stack = host.stack.filter(function (item) { return item !== dialog; });
            app.setModalOpen(host.stack.length > 0);
            dialog.destroy();
        });
        dialog.open();
    }
}
