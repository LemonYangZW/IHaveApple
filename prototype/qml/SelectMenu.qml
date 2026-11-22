import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Templates as T

// 选项菜单（倍速 / 画质）。Esc 由播放页统一处理，这里只响应点击外部关闭。
QQC.Popup {
    id: menu

    property var options: []
    property var current
    property var format: v => String(v)
    signal picked(var value)

    padding: Theme.space.xxs
    closePolicy: QQC.Popup.CloseOnPressOutsideParent

    background: Rectangle {
        radius: Theme.radius.md
        color: Theme.color.proscenium
        border.width: 1
        border.color: Theme.color.line
    }

    contentItem: Column {
        Repeater {
            model: menu.options
            delegate: T.AbstractButton {
                id: opt
                required property var modelData
                readonly property bool isCurrent: modelData === menu.current
                width: 112
                height: 32
                Accessible.name: menu.format(modelData)
                onClicked: { menu.picked(modelData); menu.close() }

                background: Rectangle {
                    radius: Theme.radius.sm
                    color: Theme.color.line
                    opacity: opt.hovered ? 1 : 0
                }
                contentItem: Row {
                    leftPadding: Theme.space.xs
                    spacing: Theme.space.xs
                    Icon {
                        width: 14
                        anchors.verticalCenter: parent.verticalCenter
                        glyph: Theme.icon.check
                        size: 12
                        color: Theme.color.crabapple
                        opacity: opt.isCurrent ? 1 : 0
                    }
                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        role: Theme.type.label
                        tabular: true
                        color: opt.isCurrent ? Theme.color.crabapple : Theme.color.subtitle
                        text: menu.format(opt.modelData)
                    }
                }
            }
        }
    }
}
