// A text field with Desktop's inline completion for @mentions, #issues and
// :emoji:. Candidates come from ui/autocompletion.py; this shows them and
// handles the keyboard, including Desktop's `onAutocompleteItemSelected`.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Controls.TextField {
    id: field

    property bool spellcheck: true
    signal itemSelected(string value)

    onTextEdited: {
        const hits = app.completionsFor(field.text, field.cursorPosition);
        completionModel.clear();
        for (let i = 0; i < hits.length; ++i) {
            completionModel.append({ "value": hits[i].value, "label": hits[i].label });
        }
        if (completionModel.count > 0) {
            completions.open();
        } else {
            completions.close();
        }
    }

    Keys.onDownPressed: event => {
        if (completions.opened) {
            completionList.incrementCurrentIndex();
        } else {
            event.accepted = false;
        }
    }
    Keys.onUpPressed: event => {
        if (completions.opened) {
            completionList.decrementCurrentIndex();
        } else {
            event.accepted = false;
        }
    }
    Keys.onReturnPressed: event => {
        if (completions.opened && completionList.currentIndex >= 0) {
            field.accept(completionModel.get(completionList.currentIndex).value);
        } else {
            event.accepted = false;
        }
    }
    Keys.onEscapePressed: completions.close()

    function accept(value) {
        field.text = app.applyCompletion(field.text, field.cursorPosition, value);
        field.cursorPosition = field.text.length;
        completions.close();
        field.itemSelected(value);
    }

    // Desktop `onAutocompletingInputContextMenu`
    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: {
            contextMenu.field = field;
            contextMenu.showSpellcheck = field.spellcheck;
            contextMenu.popup();
        }
    }

    TextContextMenu { id: contextMenu }

    ListModel { id: completionModel }

    Controls.Popup {
        id: completions

        y: field.height
        width: field.width
        implicitHeight: Math.min(Kirigami.Units.gridUnit * 12, completionList.contentHeight)
        padding: 0
        closePolicy: Controls.Popup.CloseOnEscape | Controls.Popup.CloseOnPressOutsideParent

        ListView {
            id: completionList
            anchors.fill: parent
            model: completionModel
            clip: true
            currentIndex: 0

            delegate: Controls.ItemDelegate {
                width: completionList.width
                text: model.label
                highlighted: ListView.isCurrentItem
                onClicked: field.accept(model.value)
            }
        }
    }
}
