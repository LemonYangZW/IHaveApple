import QtQuick
import QtQuick.Templates as T
import IHaveApple 1.0

// 顶部频道 tab（真人剧 / 漫剧 / 推荐）。再点一次当前 tab = 换一批节目，见 Main.pickChannel。
// 透明形式：不加任何背景块，文字直接压在画面上，选中项用海棠红下划线标出；
// 和标题栏一样跟随控件淡入淡出，鼠标静止后一起隐藏。
Item {
    id: bar

    property var model: Backend.channels
    property string current: Backend.channel
    signal picked(string channel)

    height: Theme.layout.channelBar

    // 按频道名取对应的 tab 按钮（自动化验收 / 无障碍用）
    function tabAt(name) {
        for (let i = 0; i < tabs.children.length; ++i) {
            const t = tabs.children[i]
            if (t.modelData === name) return t
        }
        return null
    }

    Row {
        id: tabs
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        height: parent.height
        spacing: Theme.space.lg

        Repeater {
            model: bar.model
            delegate: T.AbstractButton {
                id: tab
                required property string modelData
                readonly property bool selected: modelData === bar.current
                objectName: "channelTab-" + modelData
                width: tabLabel.implicitWidth
                height: bar.height
                Accessible.name: modelData
                Accessible.onPressAction: bar.picked(modelData)
                onClicked: bar.picked(modelData)

                contentItem: Item {
                    Label {
                        id: tabLabel
                        anchors.horizontalCenter: parent.horizontalCenter
                        // 下划线占 2px，文字整体上移一点，视觉上仍然居中
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.verticalCenterOffset: -1
                        role: Theme.type.label
                        text: tab.modelData
                        color: tab.selected ? Theme.color.subtitle
                             : tab.hovered ? Theme.color.subtitle70
                             : Theme.color.aside
                        Behavior on color { ColorAnimation { duration: Theme.motion.fast } }
                    }
                    // 选中下划线（与红果一致：细、短、海棠红）
                    Rectangle {
                        visible: tab.selected
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.bottom: parent.bottom
                        width: tabLabel.implicitWidth * 0.6
                        height: 2
                        radius: 1
                        color: Theme.color.crabapple
                    }
                }
                background: Item {
                    FocusRing { target: tab }
                }
            }
        }
    }
}