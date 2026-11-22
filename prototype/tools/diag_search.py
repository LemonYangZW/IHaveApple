"""临时诊断 4：验证搜索面板真的走后端检索（输入「死考」）。"""
import sys
from pathlib import Path
from PySide6.QtCore import QPoint, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonType, qmlRegisterType
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

PROTO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROTO))
OUT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else PROTO / "shots" / "diag4"
OUT.mkdir(parents=True, exist_ok=True)

from hgservice import HgService          # noqa: E402
from mpv_player import MpvPlayer         # noqa: E402
from video_item import VideoItem, bind_player    # noqa: E402

QQuickStyle.setStyle("Basic")
app = QApplication(sys.argv)
app.setOrganizationName("IHaveApple")
app.setApplicationName("IHaveApple-diag4")
QSettings().clear()
for f in (PROTO / "fonts").glob("*.ttf"):
    QFontDatabase.addApplicationFont(str(f))

player, backend = MpvPlayer(), HgService()
app._p, app._b = player, backend
bind_player(player)
qmlRegisterType(VideoItem, "IHaveApple", 1, 0, "VideoItem")
qmlRegisterSingletonType(MpvPlayer, "IHaveApple", 1, 0, "Player", lambda _e: player)
qmlRegisterSingletonType(HgService, "IHaveApple", 1, 0, "Backend", lambda _e: backend)

engine = QQmlApplicationEngine()
engine.warnings.connect(lambda ws: [print("[qml]", w.toString(), flush=True) for w in ws])
ctx = engine.rootContext()
for k, v in dict(launchPage="player", launchDrama=1, launchWidth=540, launchHeight=960,
                 launchShot=True, systemReducedMotion=True, nativeAspectResize=False).items():
    ctx.setContextProperty(k, v)
engine.load(QUrl.fromLocalFile(str(PROTO / "qml" / "Main.qml")))
win = engine.rootObjects()[0]


def click(x, y):
    win.requestActivate()
    QTest.mouseMove(win, QPoint(x, y))
    QTest.qWait(100)
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    QTest.qWait(400)


def run():
    click(310, 20)                       # 搜索按钮
    win.grabWindow().save(str(OUT / "1-panel.png"))
    from PySide6.QtQuick import QQuickItem
    field = win.findChild(QQuickItem, "searchField")
    field.setProperty("text", "死考")
    QTest.qWait(2500)
    win.grabWindow().save(str(OUT / "2a-results.png"))
    QTest.qWait(4000)
    win.grabWindow().save(str(OUT / "2-results.png"))
    click(120, 160)                      # 点第一条结果
    QTest.qWait(6000)
    win.grabWindow().save(str(OUT / "3-picked.png"))


QTimer.singleShot(9000, run)
QTimer.singleShot(25000, app.quit)
sys.exit(app.exec())