"""验收：选集面板打开后进入「本剧模式」——画面上的滚轮翻本剧上下集。

覆盖：
  1. 「查看全集」打开面板后，画面上的滚轮 = 翻集（同剧，集号 ±1）
  2. 选集面板上的滚轮不翻集，也不穿透到舞台（只滚动面板本身）
  3. 面板关掉后，滚轮恢复为换剧
  4. 面板打开时上下键同样翻集

用法：python -I tools/verify_episode_wheel.py
"""
import os
import sys

os.environ["QSG_RENDER_LOOP"] = "basic"

from PySide6.QtCore import QCoreApplication, QPoint, QPointF, QSettings, QTimer, QUrl, Qt  # noqa: E402
from PySide6.QtGui import QFontDatabase, QWheelEvent           # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlRegisterSingletonType, qmlRegisterType  # noqa: E402
from PySide6.QtQuick import QQuickItem                          # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle                # noqa: E402
from PySide6.QtTest import QTest                                # noqa: E402
from PySide6.QtWidgets import QApplication                      # noqa: E402

PROTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROTO)
OUT = os.path.join(PROTO, "shots", "ep_wheel")
os.makedirs(OUT, exist_ok=True)
FAILED = []


def log(*a):
    print(*a, flush=True)


def check(cond, label, detail=""):
    log(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILED.append(label)


from hgservice import HgService                        # noqa: E402
from mpv_player import MpvPlayer                       # noqa: E402
from video_item import VideoItem, bind_player          # noqa: E402

QQuickStyle.setStyle("Basic")
app = QApplication(sys.argv)
app.setOrganizationName("IHaveApple")
app.setApplicationName("IHaveApple-epwheel")
QSettings().clear()
for f in os.listdir(os.path.join(PROTO, "fonts")):
    if f.endswith(".ttf"):
        QFontDatabase.addApplicationFont(os.path.join(PROTO, "fonts", f))

player, backend = MpvPlayer(), HgService()
app._p, app._b = player, backend
bind_player(player)
qmlRegisterType(VideoItem, "IHaveApple", 1, 0, "VideoItem")
qmlRegisterSingletonType(MpvPlayer, "IHaveApple", 1, 0, "Player", lambda _e: player)
qmlRegisterSingletonType(HgService, "IHaveApple", 1, 0, "Backend", lambda _e: backend)

engine = QQmlApplicationEngine()
engine.warnings.connect(lambda ws: [log("[qml]", w.toString()) for w in ws])
ctx = engine.rootContext()
for k, v in dict(launchPage="player", launchDrama=0, launchWidth=540, launchHeight=960,
                 launchShot=True, systemReducedMotion=True, nativeAspectResize=False).items():
    ctx.setContextProperty(k, v)
engine.load(QUrl.fromLocalFile(os.path.join(PROTO, "qml", "Main.qml")))
win = engine.rootObjects()[0]
QQmlExpression(engine.contextForObject(win), win, "Store.muted = true").evaluate()   # 测试默认静音
backend.load_async()
STAGE = win.findChild(QQuickItem, "stage")


def ev(obj, expr):
    e = QQmlExpression(engine.contextForObject(obj), obj, expr)
    v = e.evaluate()
    if e.hasError():
        log(f"    {expr}  ERR {e.error().toString()}")
    return v[0] if isinstance(v, tuple) else v


def send_wheel(x, y, notches=1):
    """在窗口内 (x, y) 处发一个真实滚轮事件：notches>0 向下滚。"""
    pos = QPointF(x, y)
    glob = QPointF(win.x() + x, win.y() + y)
    evt = QWheelEvent(pos, glob, QPoint(0, 0), QPoint(0, -120 * notches),
                      Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QCoreApplication.sendEvent(win, evt)


def shot(name):
    log(f"[shot] {name} {win.grabWindow().save(os.path.join(OUT, name))}")


def wait_playing(timeout=40):
    t0 = QTest.qWait
    for _ in range(int(timeout * 5)):
        if ev(STAGE, "phase") == "playing":
            return True
        QTest.qWait(200)
    return False


st = {}


def step1():
    log("\n=== 准备：起播，记录起点 ===")
    check(wait_playing(), "首集已起播")
    QTest.qWait(1000)
    st["page"] = ev(win, "player")
    st["drama"] = str(ev(win, "player.dramaId"))
    st["ep"] = int(ev(win, "player.currentEp"))
    log(f"  当前 {st['drama']} 第 {st['ep'] + 1} 集")
    QTimer.singleShot(200, step2)


def step2():
    log("\n=== 1. 「查看全集」打开面板 ===")
    page = st["page"]
    ev(page, "toggleEpisodes()")
    QTest.qWait(900)
    shot("1-sheet-open.png")
    check(bool(ev(page, "episodesOpen")), "选集面板已打开")
    QTimer.singleShot(200, step3)


def step3():
    log("\n=== 2. 面板打开时滚轮 = 翻本剧下一集 ===")
    page = st["page"]
    ep_before = int(ev(page, "currentEp"))
    drama_before = str(ev(page, "dramaId"))
    ev(page, "onWheel(1)")
    QTest.qWait(3500)
    ep_after = int(ev(page, "currentEp"))
    drama_after = str(ev(page, "dramaId"))
    log(f"  第 {ep_before + 1} 集 → 第 {ep_after + 1} 集，剧 {drama_after == drama_before}")
    check(ep_after == ep_before + 1, "滚轮翻到了下一集", f"{ep_before + 1} → {ep_after + 1}")
    check(drama_after == drama_before, "没有换剧", f"{drama_after} vs {drama_before}")
    check(bool(ev(page, "episodesOpen")), "面板保持打开（仍在本剧模式）")
    shot("2-next-episode.png")
    st["ep_after"] = ep_after
    QTimer.singleShot(200, step4)


def step4():
    log("\n=== 3. 选集面板上的滚轮不翻集（只滚动面板本身，不穿透到舞台）===")
    page = st["page"]
    ep_before = int(ev(page, "currentEp"))
    drama_before = str(ev(page, "dramaId"))
    # 在选集面板区域内发真实滚轮事件，上下各滚一格
    send_wheel(int(win.width() / 2), int(win.height() - 200), notches=-1)
    QTest.qWait(1500)
    send_wheel(int(win.width() / 2), int(win.height() - 200), notches=1)
    QTest.qWait(1500)
    ep_after = int(ev(page, "currentEp"))
    log(f"  第 {ep_before + 1} 集 → 第 {ep_after + 1} 集")
    check(ep_after == ep_before, "面板上的滚轮没有翻集",
          f"{ep_before + 1} → {ep_after + 1}")
    check(str(ev(page, "dramaId")) == drama_before, "也没有换剧")
    QTimer.singleShot(200, step5)


def step5():
    log("\n=== 4. 面板打开时上下键同样翻集 ===")
    page = st["page"]
    ep_before = int(ev(page, "currentEp"))
    ev(page, "stepEpisodeOrDrama(1)")
    QTest.qWait(3500)
    ep_after = int(ev(page, "currentEp"))
    check(ep_after == ep_before + 1, "键盘上下键在面板打开时翻集",
          f"{ep_before + 1} → {ep_after + 1}")
    QTimer.singleShot(200, step6)


def step6():
    log("\n=== 5. 关掉面板后仍在本剧模式：滚轮继续翻集 ===")
    page = st["page"]
    ev(page, "toggleEpisodes()")
    QTest.qWait(800)
    check(not bool(ev(page, "episodesOpen")), "面板已关闭")
    check(bool(ev(page, "dramaMode")), "仍处于本剧模式", str(ev(page, "dramaMode")))
    ep_before = int(ev(page, "currentEp"))
    drama_before = str(ev(page, "dramaId"))
    ev(page, "onWheel(1)")
    QTest.qWait(3500)
    ep_after = int(ev(page, "currentEp"))
    drama_after = str(ev(page, "dramaId"))
    log(f"  第 {ep_before + 1} 集 → 第 {ep_after + 1} 集，剧未变={drama_after == drama_before}")
    check(ep_after == ep_before + 1, "面板关掉后滚轮仍然翻本剧的集",
          f"{ep_before + 1} → {ep_after + 1}")
    check(drama_after == drama_before, "没有换剧")
    shot("3-after-close.png")
    QTimer.singleShot(200, step7)


def step7():
    log("\n=== 6. 打开搜索页会退出本剧模式，之后滚轮换剧 ===")
    page = st["page"]
    ev(win, "library.show('search')")
    QTest.qWait(900)
    check(not bool(ev(page, "dramaMode")), "打开搜索页后退出了本剧模式",
          str(ev(page, "dramaMode")))
    ev(win, "library.close()")
    QTest.qWait(900)
    drama_before = str(ev(page, "dramaId"))
    ev(page, "onWheel(1)")
    QTest.qWait(3500)
    drama_after = str(ev(page, "dramaId"))
    ep_after = int(ev(page, "currentEp"))
    log(f"  剧 {drama_before} → {drama_after}，第 {ep_after + 1} 集")
    check(drama_after != drama_before, "滚轮恢复为换剧", f"{drama_before} → {drama_after}")
    check(ep_after == 0, "换剧后从第 1 集开始", str(ep_after))
    shot("4-back-to-feed.png")
    log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
    app.quit()


QTimer.singleShot(14000, step1)
QTimer.singleShot(120000, app.quit)
rc = app.exec()
player.shutdown()
backend.shutdown()
sys.exit(rc if not FAILED else 1)