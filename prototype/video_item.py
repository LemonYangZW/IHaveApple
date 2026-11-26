"""video_item — 把播放器当前帧交给 QML 显示（image://mpv 图片提供器）

QML 里用 VideoFrame { anchors.fill: parent }（qml/VideoFrame.qml，本质是一个 Image）。
启动时在加载 QML 之前调用 install_video(engine, player) 注册提供器。

为什么不再用自定义 QQuickItem（重写 updatePaintNode 上传纹理）：
  updatePaintNode 是 Python，在 Qt Quick 渲染线程的 sync 阶段执行，先要拿到 GIL；
  而 sync 期间 GUI 线程整段阻塞。只要别的 Python 线程（后端的预取 / 预载 / 封面、mpv 渲染线程）
  正占着 GIL，sync 就要多等几 ms 到几十 ms。播放时每一帧都要 sync 一次，GUI 线程大半时间被卡住：
  拖动窗口（系统的移动循环跑在 GUI 线程）一顿一顿，画面也跟着掉帧；暂停时没有新帧，所以不卡。
  实测（最小场景）：只多一个忙碌的 Python 线程，sync 就从约 0ms 涨到 16ms，帧数掉一半。
现在：取帧（requestImage）在 GUI 线程，纹理上传由 Qt 的 Image（C++）完成，渲染线程上不执行任何 Python。
"""

from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider


class FrameProvider(QQuickImageProvider):
    """image://mpv/<帧序号> → 播放器最新一帧。序号只用来让 Image 换地址重新取，内容总是最新帧。"""

    def __init__(self, player):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._player = player
        self._blank = QImage(2, 2, QImage.Format_RGB32)
        self._blank.fill(0)

    def requestImage(self, _id, _size, _requested):
        # QML 的 Image 设为同步加载，这里在 GUI 线程调用
        img = self._player.image
        return img if img is not None else self._blank


def install_video(engine, player):
    """在 QML 引擎上注册 image://mpv（须在加载 QML 之前调用）"""
    engine.addImageProvider("mpv", FrameProvider(player))
