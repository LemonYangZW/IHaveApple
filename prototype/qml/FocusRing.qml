import QtQuick

// 键盘焦点环：2px 海棠红描边，向外偏移 2px，只在键盘操作时显示（第 10.1 节）
// 放在控件本身或其 background 内，填充父级；target 只用于读取 visualFocus。
Rectangle {
    property Item target: parent
    property real targetRadius: Theme.radius.md

    anchors.fill: parent
    anchors.margins: -4
    radius: targetRadius + 4
    color: "transparent"
    border.width: 2
    border.color: Theme.color.crabapple
    visible: target && target.visualFocus === true
}
