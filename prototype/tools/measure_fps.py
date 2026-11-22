"""测量窗口在不同状态下每秒渲染的帧数（frameSwapped），用于排查拖动窗口掉帧。

用法：python -I tools/measure_fps.py <prototype 目录>
"""
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

PROTO = Path(sys.argv[1]).resolve()
QQuickStyle.setStyle("Basic")
app = QApplication(sys.argv)
app.setOrganizationName("IHaveApple")
app.setApplicationName("IHaveApple-verify")
QSettings().clear()
for f in (PROTO / "fonts").glob("*.ttf"):
    QFontDatabase.addApplicationFont(str(f))
engine = QQmlApplicationEngine()
for k, v in dict(launchPage="player", launchDrama=1, launchWidth=0, launchHeight=0, launchShot=True,
                 systemReducedMotion=False, nativeAspectResize=False).items():
    engine.rootContext().setContextProperty(k, v)
engine.load(QUrl.fromLocalFile(str(PROTO / "qml" / "Main.qml")))
win = engine.rootObjects()[0]
print("graphicsApi", QQuickWindow.graphicsApi(), "renderLoop env:", __import__("os").environ.get("QSG_RENDER_LOOP"))

frames = [0]
win.frameSwapped.connect(lambda: frames.__setitem__(0, frames[0] + 1))
stage = win.findChild(QQuickItem, "stage")


def ev(expr):
    return QQmlExpression(QQmlEngine.contextForObject(win), win, expr).evaluate()[0]


def measure(tag, setup, settle=1500, span=2000):
    def start():
        setup()
        QTimer.singleShot(settle, lambda: (frames.__setitem__(0, 0),
                                           QTimer.singleShot(span, lambda: print(f"{tag} : {frames[0] * 1000 / span:5.1f} fps"))))
    return start


steps = [
    ("播放中，控件显示", lambda: stage.setProperty("playing", True)),
    ("播放中，控件隐藏（静止 3s）", lambda: None),
    ("暂停", lambda: stage.setProperty("playing", False)),
    ("播放中，选集面板打开", lambda: (stage.setProperty("playing", True), ev("player.toggleEpisodes()"))),
    ("模拟 30fps 视频重绘", lambda: ev("player.closeEpisodes(), Store.simulateFrames = true")),
]
t = 800
for tag, fn in steps:
    settle = 3500 if "静止" in tag else 1500
    QTimer.singleShot(t, measure(tag, fn, settle))
    t += settle + 2300
QTimer.singleShot(t, app.quit)
app.exec()
