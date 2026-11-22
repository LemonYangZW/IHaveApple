import QtQuick
import QtQuick.Templates as T

// 分段选择：选项少（2–4 个）且需要一眼看到全部选项时使用，如设置页的画质、滚轮行为。
// options: [{ value, text }]
Rectangle {
    id: seg

    property var options: []
    property var value
    signal picked(var value)

    implicitWidth: row.implicitWidth + 4
    implicitHeight: 32
    radius: Theme.radius.md
    color: Theme.color.proscenium

    Row {
        id: row
        anchors.centerIn: parent
        Repeater {
            model: seg.options
            delegate: T.AbstractButton {
                id: option
                required property var modelData
                readonly property bool selected: modelData.value === seg.value
                implicitWidth: label.implicitWidth + Theme.space.md * 2
                implicitHeight: seg.height - 4
                Accessible.role: Accessible.RadioButton
                Accessible.checked: selected
                Accessible.name: modelData.text
                onClicked: if (!selected) seg.picked(modelData.value)

                background: Rectangle {
                    radius: Theme.radius.sm + 2
                    color: option.selected ? Theme.color.line
                         : option.hovered ? Qt.rgba(Theme.color.line.r, Theme.color.line.g, Theme.color.line.b, 0.5)
                         : "transparent"
                    Behavior on color { ColorAnimation { duration: Theme.motion.fast } }
                    FocusRing { target: option }
                }
                contentItem: Label {
                    id: label
                    role: Theme.type.label
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideNone
                    color: option.selected ? Theme.color.crabapple : option.hovered ? Theme.color.subtitle : Theme.color.aside
                    text: option.modelData.text
                }
            }
        }
    }
}
