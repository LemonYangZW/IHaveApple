import QtQuick

// 进度条：轨道高 3（悬停 5），已播放为海棠红，已缓冲为字幕白 30%，拖动手柄直径 12 只在悬停时出现。
// 按下 / 拖动时手柄跟着鼠标走，松手才发 seek：拖动中不连发 seek，
// 播放器的进度回报也不会把手柄拽回去（按下就跳的话，实时流上会来回跳）
Item {
    id: slider

    property real value: 0       // 0..1
    property real buffered: 0    // 0..1
    signal seek(real value)

    readonly property bool active: area.containsMouse || area.pressed
    readonly property bool dragging: area.pressed
    property real dragValue: 0   // 按住时鼠标所在的位置 0..1
    readonly property real shown: dragging ? dragValue : Math.min(1, value)

    implicitHeight: 16
    Accessible.role: Accessible.Slider
    Accessible.name: "播放进度"

    Rectangle {
        id: track
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width
        height: slider.active ? 5 : 3
        radius: height / 2
        color: Theme.color.line
        Behavior on height { NumberAnimation { duration: Theme.motion.fast } }

        Rectangle {
            width: parent.width * Math.min(1, slider.buffered)
            height: parent.height
            radius: parent.radius
            color: Theme.color.subtitle30
        }
        Rectangle {
            width: parent.width * slider.shown
            height: parent.height
            radius: parent.radius
            color: Theme.color.crabapple
        }
    }

    Rectangle {
        visible: slider.active
        width: 12; height: 12; radius: 6
        anchors.verticalCenter: parent.verticalCenter
        x: slider.width * slider.shown - width / 2
        color: Theme.color.subtitle
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        function follow(x) { slider.dragValue = Math.max(0, Math.min(1, x / width)) }
        onPressed: mouse => follow(mouse.x)
        onPositionChanged: mouse => { if (pressed) follow(mouse.x) }
        onReleased: slider.seek(slider.dragValue)
    }
}
