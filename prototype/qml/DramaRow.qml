import QtQuick
import QtQuick.Templates as T

// 搜索结果 / 观看历史中的一行：封面缩略图 + 剧名 + 说明。点击后切换到这部剧。
T.AbstractButton {
    id: row

    property var drama
    property string detail
    property bool current: false       // 正在播放的剧

    height: Theme.layout.dramaRow
    Accessible.name: (drama ? drama.title : "") + "，" + detail + (current ? "，正在播放" : "")

    background: Rectangle {
        radius: Theme.radius.md
        color: Theme.color.proscenium
        opacity: row.hovered ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Theme.motion.fast } }
        FocusRing { target: row }
    }

    contentItem: Item {
        Cover {
            id: cover
            x: Theme.space.xs
            anchors.verticalCenter: parent.verticalCenter
            height: Theme.layout.coverThumb
            width: Math.round(height * 3 / 4)
            radius: Theme.radius.sm
            drama: row.drama
            showTitle: false
        }
        Column {
            anchors.left: cover.right
            anchors.leftMargin: Theme.space.sm
            anchors.right: parent.right
            anchors.rightMargin: Theme.space.sm
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.space.xxs

            Label {
                width: parent.width
                role: Theme.type.label
                text: row.drama ? row.drama.title : ""
            }
            Label {
                width: parent.width
                role: Theme.type.caption
                color: Theme.color.aside
                text: row.detail
            }
            Label {
                visible: row.current
                role: Theme.type.caption
                color: Theme.color.crabapple
                text: "正在播放"
            }
        }
    }
}
