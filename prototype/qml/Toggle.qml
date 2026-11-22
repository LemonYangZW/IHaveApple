import QtQuick
import QtQuick.Templates as T

// 开关
T.AbstractButton {
    id: control
    checkable: true

    implicitWidth: 40
    implicitHeight: 20
    Accessible.role: Accessible.CheckBox
    Accessible.checked: checked

    background: Rectangle {
        radius: Theme.radius.pill
        color: control.checked ? Theme.color.crabappleDeep : Theme.color.proscenium
        border.width: control.checked ? 0 : 1
        border.color: Theme.color.line
        Behavior on color { ColorAnimation { duration: Theme.motion.fast } }

        Rectangle {
            width: 14
            height: 14
            radius: 7
            anchors.verticalCenter: parent.verticalCenter
            x: control.checked ? parent.width - width - 3 : 3
            color: control.checked ? Theme.color.subtitle : Theme.color.aside
            Behavior on x { enabled: !Theme.reducedMotion; NumberAnimation { duration: Theme.motion.fast } }
        }
        FocusRing { target: control; targetRadius: height / 2 }
    }
}
