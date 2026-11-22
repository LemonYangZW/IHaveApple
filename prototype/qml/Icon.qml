import QtQuick

// Segoe Fluent Icons 图标
Text {
    property string glyph
    property int size: 16

    text: glyph
    font.family: Theme.icon.family
    font.pixelSize: size
    color: Theme.color.subtitle
    horizontalAlignment: Text.AlignHCenter
    verticalAlignment: Text.AlignVCenter
}
