"""验收：点进度条能精准跳到点击处，不来回跳。

  · 实时流（没落盘时起播）：总时长用剧集信息里的，不随下载增长；点到还没下载的位置也能跳过去，
    期间进度条停在目标处不弹回，之后播放器换成可 seek 的文件
  · 可 seek 的文件：点哪播哪（精确到帧，不吸附关键帧）
  · 拖动：按住拖动期间不 seek、手柄跟着鼠标；松手跳到松手处

用真实鼠标点进度条。全程静音。用法：python -I tools/verify_seek.py
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
app.setApplicationName("IHaveApple-seek")
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
# 本脚本要测「没落盘的实时流」：关掉预载（它会在切集时就把目标集落盘，拿到的就是可 seek 的文件）。
# 标记为预载线程在跑，preload() 就只排队不启动
backend._preloading = True
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


def is_cached(eid):
    return any(f.startswith(eid + "_") for f in os.listdir(SDK_CACHE))


def slider():
    return win.findChild(QQuickItem, "progressSlider")


def slider_point(frac):
    """进度条上 frac 处的窗口坐标（先把鼠标移过去，唤出控件）"""
    sl = slider()
    c = sl.mapToScene(QPointF(sl.width() * frac, sl.height() / 2))
    pt = QPoint(round(c.x()), round(c.y()))
    QTest.mouseMove(win, pt)
    QTest.qWait(200)
    return pt


def seconds_at(pt):
    """窗口坐标对应的秒数（与 ProgressSlider 的换算一致）"""
    sl = slider()
    return (pt.x() - sl.mapToScene(QPointF(0, 0)).x()) / sl.width() * float(ev("duration"))


def click_at(frac):
    pt = slider_point(frac)
    target = seconds_at(pt)
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, pt)
    return target


def step1():
    global PAGE
    check(wait_until(lambda: ev("phase") == "playing", 40), "首集已起播")
    PAGE = ev("player", win)
    drama = str(ev("dramaId", PAGE))
    ids = [e["id"] for e in backend._episodes.get(drama, [])]
    cur = int(ev("currentEp", PAGE))
    t = next((i for i in range(cur + 1, len(ids)) if not is_cached(ids[i])), -1)
    check(t >= 0, "找到没落盘的集", str(t))
    if t < 0:
        return finish()

    log(f"\n=== 1. 实时流（第 {t + 1} 集，没落盘时起播） ===")
    ev(f"goTo({t})", PAGE)
    # 切集有一段淡入淡出，期间 phase 仍是上一集的 playing：以 stage.episode 换过来为准
    check(wait_until(lambda: int(ev("episode")) == t and ev("phase") == "playing" and pos() > 0.5, 40), "已起播")
    known = backend.durationOf(drama, t)
    check(not player.seekable, "播放器里是不能 seek 的实时流")
    d1 = float(ev("duration"))
    QTest.qWait(3000)
    d2 = float(ev("duration"))
    log(f"  剧集信息时长 {known}s，mpv 已下载 {player._get_float('duration') or 0:.1f}s")
    check(known > 0 and abs(d1 - known) < 0.01 and d1 == d2, "总时长 = 剧集时长且不随下载增长",
          f"{d1:.1f}s → {d2:.1f}s")
    QTest.qWait(3000)                     # SDK 开播几秒后落盘

    start = pos()
    target = click_at(0.8)
    log(f"  点击前 {start:.1f}s，目标 {target:.1f}s（远超已下载部分）")
    low = [99999.0]

    def arrived():
        low[0] = min(low[0], float(ev("position")))
        return bool(player.seekable) and not ev("switching") and abs(pos() - target) < 1.5
    ok = wait_until(arrived, 15)
    QTest.qWait(500)
    check(ok, "实时流上跳到点击处", f"播放器 {pos():.1f}s")
    check(low[0] >= target - 0.5, "等待期间进度条停在目标处、没弹回", f"最低 {low[0]:.1f}s")
    check(ev("playing") is True and not player.paused, "跳转后继续播放")
    check(abs(float(ev("duration")) - known) < 1.5, "换成文件后总时长与剧集时长一致",
          f"{float(ev('duration')):.2f}s vs {known}s")

    log("\n=== 2. 可 seek 的文件：点哪播哪 ===")
    for frac in (0.25, 0.55, 0.1):
        target = click_at(frac)
        QTest.qWait(400)
        p, ui = pos(), float(ev("position"))
        check(abs(p - target) < 0.6 and abs(ui - p) < 0.3, f"点 {frac:.0%} 处",
              f"目标 {target:.2f}s，播放器 {p:.2f}s，进度条 {ui:.2f}s")

    log("\n=== 3. 拖动：松手才跳转 ===")
    pt = slider_point(0.2)
    QTest.mousePress(win, Qt.LeftButton, Qt.NoModifier, pt)
    before = pos()
    for frac in (0.3, 0.45, 0.6):
        pt = slider_point(frac)
        QTest.qWait(150)
    shown = float(slider().property("shown"))
    check(abs(pos() - before) < 1.5, "拖动中没有 seek", f"{before:.1f}s → {pos():.1f}s")
    check(abs(shown - 0.6) < 0.02, "手柄跟着鼠标", f"{shown:.3f}")
    target = seconds_at(pt)
    QTest.mouseRelease(win, Qt.LeftButton, Qt.NoModifier, pt)
    QTest.qWait(400)
    check(abs(pos() - target) < 0.6, "松手跳到松手处", f"目标 {target:.2f}s，播放器 {pos():.2f}s")
    QTimer.singleShot(100, step2)


def step2():
    # 剧集信息的时长常比实际文件长零点几秒，实时流上进度走不到「总长 - 0.4」：要靠播放器播完的通知切下一集
    drama = str(ev("dramaId", PAGE))
    ids = [e["id"] for e in backend._episodes.get(drama, [])]
    cur = int(ev("currentEp", PAGE))
    left = [i for i in range(cur + 1, len(ids) - 1) if not is_cached(ids[i])]
    if not left:
        check(False, "找到没落盘的集（测播完）")
        return finish()
    t = min(left, key=lambda i: backend.durationOf(drama, i) or 999)
    log(f"\n=== 4. 实时流一路播完自动下一集（第 {t + 1} 集，4 倍速） ===")
    ev(f"goTo({t})", PAGE)
    check(wait_until(lambda: int(ev("episode")) == t and ev("phase") == "playing" and pos() > 0.5, 40), "已起播")
    check(not player.seekable, "播放器里是实时流")
    ev("Store.speed = 4")
    limit = (backend.durationOf(drama, t) or 200) / 4 + 30
    seen = {"pos": 0.0, "dur": 0.0}

    def advanced():
        if int(ev("episode")) == t + 1:
            return True
        seen["pos"] = max(seen["pos"], pos())
        seen["dur"] = max(seen["dur"], player._get_float("duration") or 0)
        return False
    ok = wait_until(advanced, limit)
    log(f"  文件时长 {seen['dur']:.1f}s，剧集时长 {backend.durationOf(drama, t)}s，切走前播到 {seen['pos']:.1f}s")
    check(ok, "播完后自动进入下一集", f"现在第 {int(ev('episode')) + 1} 集")
    check(seen["pos"] >= seen["dur"] - 1.5, "播到文件结尾才切走（没吞掉结尾）")
    ev("Store.speed = 1")
    finish()


def finish():
    log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
    app.quit()


QTimer.singleShot(14000, step1)
QTimer.singleShot(300000, app.quit)
rc = app.exec()
player.shutdown()
backend.shutdown()
sys.exit(rc if not FAILED else 1)
