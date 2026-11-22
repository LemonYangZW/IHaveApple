import QtQuick

// 全剧界面的顶栏：替换频道 tab 所在的那一行。
// 左侧返回（回到信息流），中间剧名 + 集数。透明叠在画面上，和标题栏一起淡入淡出。
Item {
    id: bar

    property var drama
    property int episode: 1
    property int total: 0
    signal back()

    height: Theme.layout.channelBar

    IconButton {
        id: backButton
        objectName: "dramaBarBack"
        anchors.left: parent.left
        anchors.leftMargin: Theme.space.xs
        anchors.verticalCenter: parent.verticalCenter
        glyph: Theme.icon.back
        glyphSize: 12
        tip: "返回 (Esc)"
        onClicked: bar.back()
    }

    Label {
        objectName: "dramaBarTitle"
        anchors.left: backButton.right
        anchors.right: parent.right
        anchors.leftMargin: Theme.space.xs
        anchors.rightMargin: Theme.space.md
        anchors.verticalCenter: parent.verticalCenter
        role: Theme.type.label
        elide: Text.ElideRight
        text: (bar.drama ? bar.drama.title : "")
              + (bar.total > 0 ? "  ·  第 " + bar.episode + " 集 / 共 " + bar.total + " 集" : "")
    }
}
