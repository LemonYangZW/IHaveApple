import QtQuick
import IHaveApple 1.0

// 视频表面：当前集由 VideoItem 绘制 libmpv 的画面，其余集与加载中显示封面占位。
// 保持直角矩形，不加圆角 / 蒙版 / 滤镜（设计文档第 9 节）。
Rectangle {
    id: surface

    property var drama
    property int episode: 0
    property real position: 0
    property bool live: false          // 只有当前集绘制真实画面
    property bool showCover: false     // 首帧加载中：先显示封面

    color: Theme.color.stage
    visible: !!drama && episode >= 0 && episode < drama.total

    readonly property bool showVideo: surface.live && !surface.showCover

    VideoItem {
        anchors.fill: parent
        visible: surface.showVideo
    }

    Cover {
        anchors.fill: parent
        radius: Theme.radius.video
        visible: !surface.showVideo
        drama: surface.drama
    }
}
