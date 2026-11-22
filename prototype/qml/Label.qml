import QtQuick

// 统一文字组件：通过 role 选择第 3.2 节的字号阶梯，避免各处重复设置字体。
Text {
    property var role: Theme.type.body
    property bool tabular: role === Theme.type.mono

    font.family: role.family
    font.pixelSize: role.size
    font.weight: role.weight
    font.features: tabular ? ({ "tnum": 1 }) : ({})
    lineHeightMode: Text.FixedHeight
    lineHeight: role.line
    verticalAlignment: Text.AlignVCenter
    color: Theme.color.subtitle
    elide: Text.ElideRight
}
