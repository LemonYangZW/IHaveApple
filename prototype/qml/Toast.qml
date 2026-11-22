import QtQuick

// Toast：同一时间只显示 1 条，新的替换旧的，停留 2000ms
Rectangle {
    id: toast

    function show(message) {
        label.text = message
        hideTimer.restart()
        opacity = 1
    }

    implicitWidth: label.implicitWidth + Theme.space.md * 2
    implicitHeight: 40
    radius: Theme.radius.md
    color: Theme.color.proscenium
    border.width: 1
    border.color: Theme.color.line
    opacity: 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: Theme.reducedMotion ? 0 : Theme.motion.base } }

    Accessible.role: Accessible.AlertMessage
    Accessible.name: label.text

    Label {
        id: label
        role: Theme.type.label
        anchors.centerIn: parent
    }

    Timer {
        id: hideTimer
        interval: 2000
        onTriggered: toast.opacity = 0
    }
}
