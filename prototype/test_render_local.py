"""离线渲染验证：直接播本地 mp4，检查 set_target_size 是否生效、CPU 占用如何

用法：python test_render_local.py
"""
import os
import sys
import time
from pathlib import Path

# 结尾要 grabWindow()：改用 basic 渲染循环，避免与 VideoItem 的 GIL 死锁（见 video_item.py）
os.environ["QSG_RENDER_LOOP"] = "basic"

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView
from PySide6.QtQml import qmlRegisterSingletonInstance, qmlRegisterType

sys.path.insert(0, str(Path(__file__).parent))
from mpv_player import MpvPlayer          # noqa: E402
import video_item                          # noqa: E402
from video_item import VideoItem           # noqa: E402

MP4 = r"E:\projects\hongguo\hgd\cache\7701288600888937497_1080p.mp4"

app = QGuiApplication(sys.argv)

player = MpvPlayer()
video_item.bind_player(player)

qmlRegisterSingletonInstance(MpvPlayer, "IHaveApple", 1, 0, "Player", player)
qmlRegisterType(VideoItem, "IHaveApple", 1, 0, "VideoItem")

view = QQuickView()
view.setSource(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "Stage.qml")))
print("QML errors:", [str(e) for e in view.errors()], flush=True)
view.resize(430, 760)
view.show()

state = {"frames": 0, "first_render_size": None}
t0 = time.time()


def on_frame():
    state["frames"] += 1
    if state["first_render_size"] is None and player.image is not None:
        state["first_render_size"] = (player.image.width(), player.image.height())


player.frameReady.connect(on_frame)
player.setMute(True)    # 测试默认静音
player.load_file(MP4)
player.play()


def report():
    dt = time.time() - t0
    print(f"\n=== 渲染统计 ===")
    print(f"  帧数        : {state['frames']}  ({state['frames']/dt:.1f} fps)")
    print(f"  渲染尺寸    : {state['first_render_size']}")
    print(f"  控件尺寸    : {int(view.width())}x{int(view.height())} (dpr={view.devicePixelRatio()})")
    print(f"  player 目标 : {player._target_wh}")
    view.grabWindow().save(str(Path(__file__).parent / "render_local.png"))
    print("  截图已存：render_local.png")
    app.quit()


QTimer.singleShot(12000, report)
sys.exit(app.exec())