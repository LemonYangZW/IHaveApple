import QtQuick
import QtQuick.Templates as T

// 按钮（第 5.1 节）
//   primary   海棠深填充 + 字幕白文字，每个视图最多 1 个
//   secondary 透明 + 台缝色描边
T.AbstractButton {
    id: control

    property string variant: "secondary"
    property string iconGlyph: ""

    readonly property color fillColor: variant === "primary" ? Theme.color.crabappleDeep
                                     : "transparent"
    property color inkColor: Theme.color.subtitle

    implicitHeight: Theme.layout.button
    implicitWidth: contentItem.implicitWidth + leftPadding + rightPadding
    leftPadding: Theme.space.md
    rightPadding: Theme.space.md
    opacity: enabled ? 1 : 0.4
    scale: pressed ? 0.98 : 1
    Behavior on scale { NumberAnimation { duration: Theme.motion.fast } }

    background: Rectangle {
        radius: Theme.radius.md
        color: control.fillColor
        border.width: control.variant === "secondary" ? 1 : 0
        border.color: Theme.color.line

        // 悬停提亮 8%
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: Theme.color.subtitle
            opacity: control.hovered ? 0.08 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.motion.fast } }
        }
        FocusRing { target: control }
    }

    // 全宽按钮时内容居中
    contentItem: Item {
        implicitWidth: row.implicitWidth
        implicitHeight: row.implicitHeight

        Row {
            id: row
            anchors.centerIn: parent
            spacing: Theme.space.xs
            Icon {
                visible: control.iconGlyph !== ""
                glyph: control.iconGlyph
                color: control.inkColor
                anchors.verticalCenter: parent.verticalCenter
            }
            Label {
                role: Theme.type.label
                text: control.text
                color: control.inkColor
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
