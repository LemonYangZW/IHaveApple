"""验收：画面上按住上下拖动，画卷跟手。

  · 拖动中画卷（连同底部剧名）跟着鼠标走；信息流里下方露出的是剧单下一部的封面，本剧模式里是下一集
  · 松手：拖过 layout.swipe → 续滑翻过去；不够远 → 弹回；不够远但甩得快 → 也翻过去
  · 首尾集往外拖带阻尼，松手弹回并提示
  · 拖动不触发单击暂停；单击暂停照常

关闭「减少动画」以覆盖动画路径。用真实鼠标拖。全程静音。用法：python -I tools/verify_swipe.py
"""
import os
import sys

os.environ["QSG_RENDER_LOOP"] = "basic"

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QFontDatabase                          # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlRegisterSingletonType, qmlRegisterType  # noqa: E402
from PySide6.QtQuick import QQuickItem                           # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle                 # noqa: E402
from PySide6.QtTest import QTest                                 # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

PROTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROTO)
FAILED = []


def log(*a):
    print(*a, flush=True)


def check(cond, label, detail=""):
    log(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILED.append(label)


from hgservice import SDK_CACHE, HgService             # noqa: E402
from mpv_player import MpvPlayer                       # noqa: E402
from video_item import VideoItem, bind_player          # noqa: E402

QQuickStyle.setStyle("Basic")
app = QApplication(sys.argv)
app.setOrganizationName("IHaveApple")
app.setApplicationName("IHaveApple-swipe")
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
                 launchShot=True, systemReducedMotion=False, nativeAspectResize=False).items():
    ctx.setContextProperty(k, v)
engine.load(QUrl.fromLocalFile(os.path.join(PROTO, "qml", "Main.qml")))
win = engine.rootObjects()[0]
QQmlExpression(engine.contextForObject(win), win, "Store.muted = true").evaluate()   # 测试默认静音
backend.load_async()
STAGE = win.findChild(QQuickItem, "stage")
PAGE = None


def ev(expr, obj=None):
    obj = obj or STAGE
    e = QQmlExpression(engine.contextForObject(obj), obj, expr)
    v = e.evaluate()
    if e.hasError():
        log(f"    {expr}  ERR {e.error().toString()}")
    return v[0] if isinstance(v, tuple) else v


def wait_until(fn, timeout):
    for _ in range(int(timeout * 10)):
        if fn():
            return True
        QTest.qWait(100)
    return False


def pos():
    return player._get_float("time-pos") or 0.0


def stage_point(fx, fy):
    c = STAGE.mapToScene(QPointF(STAGE.width() * fx, STAGE.height() * fy))
    return QPoint(round(c.x()), round(c.y()))


START = (0.5, 0.45)


def press():
    p0 = stage_point(*START)
    QTest.mouseMove(win, p0)
    QTest.qWait(50)
    QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, p0)
    return p0


def move_to(p0, dx, dy, steps, wait):
    for i in range(1, steps + 1):
        QTest.mouseMove(win, QPoint(p0.x() + round(dx * i / steps), p0.y() + round(dy * i / steps)))
        QTest.qWait(wait)


def release(p0, dx, dy):
    QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, QPoint(p0.x() + round(dx), p0.y() + round(dy)))


def slow_drag(dx, dy):
    """慢慢拖、停住再松手（不算甩）"""
    p0 = press()
    move_to(p0, dx, dy, 12, 40)
    QTest.qWait(200)
    release(p0, dx, dy)


def reel_y():
    return STAGE.findChild(QQuickItem, "reel").y()


def settle():
    QTest.qWait(700)        # 等续滑 / 弹回动画和单击判定（250ms）


def step1():
    global PAGE
    check(wait_until(lambda: ev("phase") == "playing", 40), "首集已起播")
    PAGE = ev("player", win)
    swipe = int(ev("Theme.layout.swipe"))
    QTest.qWait(1000)
    ids = [str(i) for i in ev("Backend.feedIds", win)]
    d0 = str(ev("dramaId", PAGE))
    nxt = ids[(ids.index(d0) + 1) % len(ids)]

    log("\n=== 1. 信息流：拖动中画卷跟手，下方是剧单下一部 ===")
    p0 = press()
    move_to(p0, 0, -150, 10, 30)
    y = reel_y()
    check(abs(y + 150) < 2, "画卷跟着鼠标走", f"reel.y = {y:.0f}（拖了 -150）")
    check(str(ev("nextDrama ? nextDrama.id : ''")) == nxt, "下方邻居是剧单的下一部", nxt)
    info = STAGE.findChild(QQuickItem, "dramaInfo")
    shift = info.mapToItem(STAGE, QPointF(0, 0)).y() - info.y()
    check(abs(shift - y) < 2, "底部剧名跟着画卷走", f"偏移 {shift:.0f}")
    check(ev("playing") is True, "拖动中没有暂停")
    QTest.qWait(200)
    release(p0, 0, -150)
    QTest.qWait(80)
    mid = reel_y()
    check(-float(ev("height")) < mid < -150 - 1 or str(ev("dramaId", PAGE)) == nxt, "松手后从当前位置续滑（不跳回 0 重来）",
          f"80ms 后 reel.y = {mid:.0f}")
    settle()
    check(str(ev("dramaId", PAGE)) == nxt, "翻到剧单下一部", f"{d0} → {ev('dramaId', PAGE)}")
    check(reel_y() == 0, "换完画卷归位")
    check(ev("playing") is True, "没有触发暂停")
    check(wait_until(lambda: ev("phase") == "playing", 40), "新剧起播")

    log("\n=== 2. 拖得不够远：弹回 ===")
    d1 = str(ev("dramaId", PAGE))
    p0 = press()
    move_to(p0, 0, swipe - 20, 12, 40)
    check(abs(reel_y() - (swipe - 20)) < 2, "下拖时画卷跟手", f"reel.y = {reel_y():.0f}")
    QTest.qWait(200)
    release(p0, 0, swipe - 20)
    QTest.qWait(80)
    check(0 < reel_y() < swipe - 20, "松手后正在弹回", f"80ms 后 reel.y = {reel_y():.0f}")
    settle()
    check(str(ev("dramaId", PAGE)) == d1 and reel_y() == 0, "没换剧、画卷回到原位")
    check(ev("playing") is True, "没有触发暂停")

    log("\n=== 3. 快速甩：距离不够也翻过去 ===")
    p0 = press()
    move_to(p0, 0, swipe - 20, 4, 8)
    release(p0, 0, swipe - 20)
    settle()
    prev = ids[(ids.index(d1) - 1) % len(ids)]
    check(str(ev("dramaId", PAGE)) == prev, "快速下甩换到上一部", f"{d1} → {ev('dramaId', PAGE)}")
    check(wait_until(lambda: ev("phase") == "playing", 40), "起播")

    log("\n=== 4. 横向为主：画卷不动 ===")
    d2 = str(ev("dramaId", PAGE))
    p0 = press()
    move_to(p0, swipe + 60, -(swipe + 10), 10, 30)
    check(reel_y() == 0, "画卷不跟")
    release(p0, swipe + 60, -(swipe + 10))
    settle()
    check(str(ev("dramaId", PAGE)) == d2 and ev("playing") is True, "不换、不暂停")

    log("\n=== 5. 单击暂停照常 ===")
    p = stage_point(*START)
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, p)
    settle()
    check(ev("playing") is False, "单击暂停")
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, p)
    settle()
    check(ev("playing") is True, "再单击继续")

    log("\n=== 6. 本剧模式：翻集 + 首集阻尼 ===")
    ev("enterDramaView()", PAGE)
    QTest.qWait(300)
    if int(ev("currentEp", PAGE)) != 0:
        ev("goTo(0)", PAGE)
        settle()
    check(int(ev("currentEp", PAGE)) == 0, "在第 1 集")
    check(not ev("swipeDramas"), "邻居换成本剧上下集")
    p0 = press()
    move_to(p0, 0, 150, 10, 30)
    y = reel_y()
    check(abs(y - 50) < 3, "第 1 集往下拖带阻尼（只跟三分之一）", f"拖了 150，reel.y = {y:.0f}")
    QTest.qWait(200)
    release(p0, 0, 150)
    settle()
    check(int(ev("currentEp", PAGE)) == 0 and reel_y() == 0, "松手弹回、仍是第 1 集")
    slow_drag(0, -(swipe + 60))
    settle()
    check(int(ev("currentEp", PAGE)) == 1 and str(ev("dramaId", PAGE)) == d2, "上拖翻到第 2 集",
          f"第 {int(ev('currentEp', PAGE)) + 1} 集")
    check(reel_y() == 0, "画卷归位")
    check(wait_until(lambda: ev("phase") == "playing", 40), "第 2 集起播")
    finish()


def finish():
    log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
    app.quit()


QTimer.singleShot(14000, step1)
QTimer.singleShot(200000, app.quit)
rc = app.exec()
player.shutdown()
backend.shutdown()
sys.exit(rc if not FAILED else 1)
