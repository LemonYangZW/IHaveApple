import QtQuick

// 全剧终：只提供「从第 1 集重看」
Rectangle {
    id: root

    property var drama
    signal replay()

    color: Theme.color.scrim

    Column {
        anchors.centerIn: parent
        width: parent.width - Theme.space.lg * 2
        spacing: Theme.space.lg

        Column {
            width: parent.width
            Label { width: parent.width; horizontalAlignment: Text.AlignHCenter; role: Theme.type.h1; text: "全剧终" }
            Label {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                role: Theme.type.caption
                color: Theme.color.aside
                text: root.drama ? "你看完了全部 " + root.drama.total + " 集" : ""
            }
        }

        IhaButton {
            anchors.horizontalCenter: parent.horizontalCenter
            variant: "primary"
            iconGlyph: Theme.icon.refresh
            text: "从第 1 集重看"
            onClicked: root.replay()
        }
    }
}
