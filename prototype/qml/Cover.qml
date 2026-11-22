import QtQuick

// 海报：hgservice 已经把服务端封面（HEIC）转码并缓存成本地 JPEG，这里贴图；
// 没有封面 / 还没转好时，退回「两种主色渐变 + 得意黑剧名」的占位美术。
Rectangle {
    id: cover

    property var drama
    property bool showTitle: true

    readonly property bool hasArt: art.status === Image.Ready

    radius: Theme.radius.md
    clip: true
    gradient: Gradient {
        GradientStop { position: 0.0; color: cover.drama ? cover.drama.covers[1] : Theme.color.proscenium }
        GradientStop { position: 1.0; color: cover.drama ? cover.drama.covers[0] : Theme.color.wing }
    }

    // 真实封面：异步解码，按显示尺寸解码，避免整张大图进内存
    Image {
        id: art
        anchors.fill: parent
        visible: cover.hasArt
        asynchronous: true
        cache: true
        fillMode: Image.PreserveAspectCrop
        source: cover.drama && cover.drama.cover ? cover.drama.cover : ""
        sourceSize.width: Math.max(1, Math.round(cover.width * 2))
        sourceSize.height: Math.max(1, Math.round(cover.height * 2))
    }

    // 占位美术：模拟海报上的人物剪影光斑
    Rectangle {
        visible: !cover.hasArt
        width: parent.width * 0.9
        height: width
        radius: width / 2
        x: parent.width * 0.3
        y: -parent.height * 0.08
        color: Theme.color.subtitle
        opacity: 0.08
    }

    // 占位剧名：真实海报上本来就有剧名，不再叠字
    Text {
        visible: cover.showTitle && cover.drama && !cover.hasArt
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: Math.max(6, cover.width * 0.07)
        text: cover.drama ? cover.drama.title : ""
        wrapMode: Text.WrapAnywhere
        maximumLineCount: 3
        font.family: Theme.font.display
        font.pixelSize: Math.max(10, Math.round(cover.width * 0.13))
        lineHeight: 1.05
        color: Theme.color.subtitle
        style: Text.Raised
        styleColor: Theme.color.stage60
    }
}