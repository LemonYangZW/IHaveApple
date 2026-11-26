import QtQuick
import IHaveApple 1.0

// 视频画面：libmpv 的当前帧经 image://mpv 交给 Image 显示（提供器见 video_item.py）。
// 纹理上传由 Image 自己（C++）完成，Qt Quick 渲染线程上不跑 Python —— 否则每帧 sync 都要等 GIL，
// 播放时 GUI 线程被反复卡住，拖动窗口卡顿、画面掉帧。
// 必须同步加载：异步时每帧先清空再补上，画面会闪；不缓存：每帧地址都不同，缓存只会堆积。
Image {
    id: frame

    asynchronous: false
    cache: false
    smooth: true
    fillMode: Image.PreserveAspectFit
    // 不可见时不读帧序号：绑定就不依赖它，后台的表面不会每帧重新求值、取帧
    source: frame.visible && Player.frameSerial > 0 ? "image://mpv/" + Player.frameSerial : ""

    // 把物理像素尺寸告诉播放器：按控件大小输出，界面不做二次缩放。
    // 几个表面都和舞台一样大，谁报都一样；不看是否可见 —— 首帧到达前画面还隐藏着，也得先报上尺寸
    readonly property size targetSize: Qt.size(Math.round(width * Screen.devicePixelRatio),
                                               Math.round(height * Screen.devicePixelRatio))
    onTargetSizeChanged: {
        if (targetSize.width > 0 && targetSize.height > 0)
            Player.set_target_size(targetSize.width, targetSize.height)
    }
}
