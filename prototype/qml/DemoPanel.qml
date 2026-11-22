import QtQuick
import QtQuick.Controls as QQC

// 仅原型：切换各种界面状态，方便评审。正式版删除。
QQC.Popup {
    id: demo

    signal action(string name)

    anchors.centerIn: QQC.Overlay.overlay
    width: Math.min(420, QQC.Overlay.overlay.width - Theme.space.xl)
    padding: Theme.space.lg
    modal: true
    focus: true                  // CloseOnEscape 只在弹窗持有焦点时生效
    closePolicy: QQC.Popup.CloseOnEscape | QQC.Popup.CloseOnPressOutside

    QQC.Overlay.modal: Rectangle { color: Theme.color.scrim }
    background: Rectangle {
        radius: Theme.radius.lg
        color: Theme.color.wing
        border.width: 1
        border.color: Theme.color.line
    }

    readonly property var playerStates: [
        { key: "slow", text: "首帧慢（显示封面 + 加载环）" },
        { key: "buffering", text: "播放中缓冲" },
        { key: "error", text: "播放失败" },
        { key: "codec", text: "编码不支持，自动降级" },
        { key: "end", text: "全剧终" }
    ]

    contentItem: Column {
        spacing: Theme.space.md

        Column {
            spacing: Theme.space.xxs
            Label { role: Theme.type.h2; text: "界面状态演示" }
            Label { role: Theme.type.caption; color: Theme.color.aside; text: "仅原型使用（Ctrl+Shift+D）。" }
        }

        Flow {
            width: parent.width
            spacing: Theme.space.xs
            Repeater {
                model: demo.playerStates
                delegate: IhaButton {
                    required property var modelData
                    variant: "secondary"
                    text: modelData.text
                    onClicked: { demo.action(modelData.key); demo.close() }
                }
            }
        }

        Rectangle { width: parent.width; height: 1; color: Theme.color.line }

        DemoToggle { text: "网络已断开"; checked: Store.offline; onToggled: v => Store.offline = v }
        DemoToggle { text: "减少动画"; checked: Theme.reducedMotion; onToggled: v => Theme.reducedMotion = v }
        DemoToggle { text: "模拟 30fps 视频重绘（测试拖动窗口）"; checked: Store.simulateFrames; onToggled: v => Store.simulateFrames = v }
    }

    component DemoToggle: Item {
        id: dt
        property string text
        property bool checked
        signal toggled(bool value)
        width: parent ? parent.width : 0
        height: 28
        Label { anchors.verticalCenter: parent.verticalCenter; role: Theme.type.label; text: dt.text }
        Toggle {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            checked: dt.checked
            Accessible.name: dt.text
            onToggled: dt.toggled(checked)
        }
    }
}
