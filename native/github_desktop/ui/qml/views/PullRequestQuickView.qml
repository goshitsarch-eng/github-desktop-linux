// Desktop's PullRequestQuickView: hovering a pull request in the list shows
// its title, author and body without leaving the app.

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.kirigami as Kirigami

Controls.Popup {
    id: quickView

    property var pullRequest: null

    width: Kirigami.Units.gridUnit * 24
    padding: Kirigami.Units.largeSpacing
    modal: false
    closePolicy: Controls.Popup.CloseOnEscape | Controls.Popup.CloseOnPressOutsideParent

    ColumnLayout {
        anchors.fill: parent
        spacing: Kirigami.Units.smallSpacing

        Kirigami.Heading {
            Layout.fillWidth: true
            level: 4
            text: quickView.pullRequest ? quickView.pullRequest.title : ""
            wrapMode: Text.WordWrap
        }

        Controls.Label {
            Layout.fillWidth: true
            text: quickView.pullRequest
                ? qsTr("#%1 opened %2 by %3")
                    .arg(quickView.pullRequest.number)
                    .arg(quickView.pullRequest.relativeTime)
                    .arg(quickView.pullRequest.author)
                : ""
            opacity: 0.75
            font: Kirigami.Theme.smallFont
        }

        Controls.Label {
            Layout.fillWidth: true
            text: quickView.pullRequest ? app.pullRequestBody(quickView.pullRequest.number) : ""
            textFormat: Text.RichText
            wrapMode: Text.WordWrap
            onLinkActivated: link => app.openUrl(link)
        }
    }
}
