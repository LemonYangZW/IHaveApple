"""测量真实视频播放时的帧节奏与 GUI 线程的空闲程度（排查"拖动窗口卡""帧率低"）。

- 出帧间隔：渲染线程每产出一帧的间隔，应稳定在源帧间隔（30fps → 33.3ms）
- 上屏间隔：窗口 frameSwapped 的间隔，应与出帧一致，不应有成倍的长间隔
- GUI 线程最长卡顿：2ms 定时器的最大迟到量。系统移动窗口的循环跑在 GUI 线程上，
  这个值大，拖动窗口就会卡

用法：python tools/probe_video.py <mp4> [秒数]
"""
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import qmlRegisterType  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402

import video_item  # noqa: E402
from mpv_player import MpvPlayer  # noqa: E402

app = QGuiApplication(sys.argv)
player = MpvPlayer()
video_item.bind_player(player)
qmlRegisterType(video_item.VideoItem, "IHaveApple", 1, 0, "VideoItem")

view = QQuickView()
view.setResizeMode(QQuickView.SizeRootObjectToView)
view.setSource(QUrl.fromLocalFile(str(ROOT / "qml" / "SurfaceOnly.qml")))  # 绝对路径字符串会被当成 "e:" 协议的 URL
view.resize(540, 960)
view.show()

frames, swaps, lag = [], [], [0.0]
player.frameReady.connect(lambda: frames.append(time.perf_counter()))
view.frameSwapped.connect(lambda: swaps.append(time.perf_counter()))

last = [time.perf_counter()]


def heartbeat():
    now = time.perf_counter()
    if len(frames) > 15:        # 跳过起播阶段
        lag[0] = max(lag[0], (now - last[0]) * 1000 - 2)
    last[0] = now


hb = QTimer()
hb.setTimerType(Qt.PreciseTimer)
hb.timeout.connect(heartbeat)
hb.start(2)

player.setMute(True)    # 测试默认静音
player.load_file(sys.argv[1])
player.play()


def stats(ts):
    d = [(b - a) * 1000 for a, b in zip(ts[15:], ts[16:])]
    if not d:
        return f"样本不足（共 {len(ts)} 次）"
    return f"{len(d)} 次  平均 {statistics.mean(d):.1f}ms  stdev {statistics.pstdev(d):.1f}ms  最大 {max(d):.1f}ms"


def report():
    print(f"源帧率 {player._get_float('container-fps')}  mpv 丢帧 {player._get_int('frame-drop-count')}")
    print(f"源尺寸 {player._video_wh}  输出 {player._wh}  控件目标 {player._target_wh}")
    print(f"出帧间隔：{stats(frames)}")
    print(f"上屏间隔：{stats(swaps)}")
    print(f"GUI 线程最长卡顿：{lag[0]:.1f}ms")
    app.quit()


QTimer.singleShot(int(float(sys.argv[2]) * 1000) if len(sys.argv) > 2 else 10000, report)
app.exec()
player.shutdown()
