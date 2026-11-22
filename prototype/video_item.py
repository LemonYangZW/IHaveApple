"""video_item — 把播放器当前帧作为纹理显示在 QML 中

不依赖 QtMultimedia：QQuickItem + QSGSimpleTextureNode，QImage 直接上传为纹理。
（QQuickPaintedItem 会先用 QPainter 把整帧再画一遍，每帧多一次整帧拷贝。）
QML 用法（注册为 IHaveApple.VideoItem）：
    VideoItem { anchors.fill: parent }

注意（死锁）：updatePaintNode 是 Python 代码，在 Qt Quick 渲染线程执行，需要拿 GIL。
GUI 线程若在 Python 里调用会同步等待渲染线程的接口（典型是 window.grabWindow()），
PySide 不释放 GIL → 两个线程互等。需要截图的脚本要在创建 QApplication 前设置
QSG_RENDER_LOOP=basic（渲染改在 GUI 线程）。正常播放走事件循环，不受影响。
"""

from PySide6.QtCore import QRectF
from PySide6.QtQuick import QQuickItem, QSGSimpleTextureNode, QSGTexture

# 由 main.py 注入的播放器实例（全局单例）
_player = None


def bind_player(p):
    """注入播放器（全进程一个播放器）"""
    global _player
    _player = p


class VideoItem(QQuickItem):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFlag(QQuickItem.ItemHasContents, True)
        self._shown = None           # 已上传为纹理的那一帧，避免重复上传
        # 尺寸变化时把物理像素尺寸告诉播放器 → 播放器按这个尺寸输出，UI 不做二次缩放
        self.widthChanged.connect(self._report_size)
        self.heightChanged.connect(self._report_size)
        self.windowChanged.connect(self._report_size)
        if _player is not None:
            _player.frameReady.connect(self._on_frame)

    def _on_frame(self):
        if self.isVisible():
            self.update()

    def _report_size(self, *_):      # windowChanged 会带一个 window 参数
        win = self.window()
        if _player is None or win is None:
            return
        dpr = win.devicePixelRatio()
        w, h = round(self.width() * dpr), round(self.height() * dpr)
        if w > 0 and h > 0:
            _player.set_target_size(w, h)

    def updatePaintNode(self, node, _data):
        # 在 Qt Quick 渲染线程调用（此时 GUI 线程被同步阻塞），只做纹理上传
        img = _player.image if _player is not None else None
        if img is None or img.isNull():
            return node
        if node is None:
            node = QSGSimpleTextureNode()
            node.setOwnsTexture(True)          # 换纹理 / 销毁节点时由 Qt 释放旧纹理
            node.setFiltering(QSGTexture.Filtering.Linear)
            self._shown = None
        if img is not self._shown:
            node.setTexture(self.window().createTextureFromImage(img))
            self._shown = img
        node.setRect(self._fit(img.width(), img.height()))
        return node

    def _fit(self, sw, sh):
        """画面撑满控件（9:16 源与 9:16 控件比例一致，不需要 letterbox）"""
        tw, th = self.width(), self.height()
        if sw <= 0 or sh <= 0 or tw <= 0 or th <= 0:
            return QRectF(0, 0, tw, th)
        src_ratio = sw / sh
        if tw / th > src_ratio:
            w = th * src_ratio
            return QRectF((tw - w) / 2, 0, w, th)
        h = tw / src_ratio
        return QRectF(0, (th - h) / 2, tw, h)
