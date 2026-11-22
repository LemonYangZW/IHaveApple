import QtQuick
import QtQuick.Controls as QQC

// 统一 tooltip：悬停 600ms 后出现，文字里带快捷键
QQC.ToolTip {
    id: tip
    delay: 600
    padding: Theme.space.xs
    leftPadding: Theme.space.sm
    rightPadding: Theme.space.sm

    background: Rectangle {
        color: Theme.color.proscenium
        radius: Theme.radius.sm
        border.width: 1
        border.color: Theme.color.line
    }
    contentItem: Label {
        role: Theme.type.caption
        text: tip.text
    }
}
