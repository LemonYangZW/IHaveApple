import QtQuick
import IHaveApple 1.0

// 视频表面：当前集由 VideoItem 绘制 libmpv 的画面，其余集与加载中显示占位。
// 占位优先用这一集的首帧图（预载落盘后抽出），没有才用剧封面：起播后画面从同一帧接上，看不出切换。
// 保持直角矩形，不加圆角 / 蒙版 / 滤镜（设计文档第 9 节）。
Rectangle {
    id: surface

    property var drama
    property int episode: 0
    property real position: 0
    property bool live: false          // 只有当前集绘制真实画面
    property bool showCover: false     // 首帧加载中：先显示占位
    property string poster: ""         // 这一集的首帧图（Backend.posterOf），空 = 还没有

    color: Theme.color.stage
    visible: !!drama && episode >= 0 && episode < drama.total

    readonly property bool showVideo: surface.live && !surface.showCover

    VideoItem {
        anchors.fill: parent
        visible: surface.showVideo
    }

    // 首帧图：和 VideoItem 一样按比例完整显示，起播那一下画面位置不跳。
    // 不设 sourceSize：几个表面共用同一份缓存，切集时当前表面换成这张图是同步命中，不会先闪一下封面
    Image {
        id: posterArt
        anchors.fill: parent
        visible: !surface.showVideo && status === Image.Ready
        asynchronous: true
        fillMode: Image.PreserveAspectFit
        source: surface.poster
    }

    Cover {
        anchors.fill: parent
        radius: Theme.radius.video
        visible: !surface.showVideo && !posterArt.visible
        drama: surface.drama
    }
}
