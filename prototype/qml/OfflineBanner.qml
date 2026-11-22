import QtQuick

// 离线横幅：标题栏下方，高 32
Rectangle {
    height: 32
    color: Theme.color.proscenium

    Row {
        anchors.centerIn: parent
        spacing: Theme.space.xs
        Icon { glyph: Theme.icon.info; size: 14; color: Theme.color.danger; anchors.verticalCenter: parent.verticalCenter }
        Label { role: Theme.type.label; text: "网络已断开，连接后会自动继续播放。" }
    }
}
