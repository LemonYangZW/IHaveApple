import QtQuick
import QtQuick.Templates as T

// 底部信息区：剧名 + 简介 + 集数 + 「进入查看全剧」。
// 剧名和简介从标题栏搬到这里，宽度够、可换行，长剧名能完整显示。
// 常驻显示（阅读信息是刚需），背景是从透明到舞台黑的静态渐变，不使用模糊。
Item {
    id: info

    property var drama
    property int episode: 1
    property int total: 0
    property bool inDramaView: false   // 已在全剧界面：入口按钮隐藏
    signal showAll()

    readonly property string title: drama ? drama.title : ""
    readonly property string desc: drama ? (drama.desc || "") : ""
    readonly property string detail: total > 0 ? "第 " + episode + " 集 / 共 " + total + " 集" : ""
    readonly property bool hasContent: title !== "" && String(drama ? drama.id : "") !== "loading"

    // 渐变向上延伸，让文字离开画面主体；信息区本体只占文字高度
    height: Theme.layout.dramaInfo
    visible: hasContent && !inDramaView

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: info.height + Theme.layout.controlsBar
        gradient: Gradient {
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 1.0; color: Theme.color.stage60 }
        }
    }

    Column {
        id: textColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: Theme.space.md
        anchors.rightMargin: Theme.space.md
        spacing: Theme.space.xxs

        Label {
            objectName: "dramaTitle"
            width: parent.width
            role: Theme.type.label
            // 长剧名最多两行，超出省略；宽度够就不再被截断
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
            text: info.title
        }
        Label {
            objectName: "dramaDesc"
            width: parent.width
            visible: info.desc !== ""
            role: Theme.type.caption
            color: Theme.color.subtitle70
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
            text: info.desc
        }
        // 集数 + 进入查看全剧
        Row {
            spacing: Theme.space.sm
            Label {
                anchors.verticalCenter: parent.verticalCenter
                role: Theme.type.caption
                color: Theme.color.aside
                text: info.detail
            }
            T.AbstractButton {
                id: showAllButton
                objectName: "showAllButton"
                visible: !info.inDramaView
                anchors.verticalCenter: parent.verticalCenter
                height: Theme.space.sm + Theme.space.xs
                width: showAllLabel.implicitWidth
                Accessible.name: "进入查看全剧"
                onClicked: info.showAll()

                contentItem: Label {
                    id: showAllLabel
                    anchors.centerIn: parent
                    role: Theme.type.label
                    color: showAllButton.hovered ? Theme.color.crabapple : Theme.color.crabappleDeep
                    text: "进入查看全剧 ›"
                }
                background: Item { FocusRing { target: showAllButton } }
                Tip { text: "进入全剧，滚动切换上下集"; visible: showAllButton.hovered }
            }
        }
    }
}