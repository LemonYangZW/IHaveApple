import QtQuick
import QtQuick.Templates as T

// 图标按钮：32×32，旁白灰 → 悬停字幕白。tip 中应包含快捷键。
T.AbstractButton {
    id: control

    property string glyph
    property string tip: ""
    property int glyphSize: 16
    property bool active: false        // 选中态（如已追剧）显示海棠红
    property bool closeStyle: false    // 窗口关闭按钮：悬停为海棠深底

    implicitWidth: Theme.layout.iconButton
    implicitHeight: Theme.layout.iconButton
    Accessible.name: tip

    background: Rectangle {
        radius: control.closeStyle ? 0 : Theme.radius.md
        color: control.closeStyle ? Theme.color.crabappleDeep : Theme.color.subtitle
        opacity: control.closeStyle ? (control.hovered ? 1 : 0)
                                    : (control.pressed ? 0.12 : control.hovered ? 0.08 : 0)
        Behavior on opacity { NumberAnimation { duration: Theme.motion.fast } }
    }

    contentItem: Icon {
        glyph: control.glyph
        size: control.glyphSize
        color: control.active ? Theme.color.crabapple
             : control.hovered ? Theme.color.subtitle
             : Theme.color.aside
        Behavior on color { ColorAnimation { duration: Theme.motion.fast } }
    }

    FocusRing { target: control; targetRadius: Theme.radius.md }

    Tip {
        text: control.tip
        visible: control.hovered && control.tip !== ""
    }
}
