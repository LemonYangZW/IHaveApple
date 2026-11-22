"""验收：换剧 / 换集时，旧节目立即停止，不会在新节目加载期间继续播放（出声）。

做法：先把当前节目 seek 到 30s，再换剧 / 换集；在新节目还在加载（stage.phase == loading）期间
每 50ms 采样一次 mpv 的 time-pos，只要还能读到 >= 25s 的位置，就说明旧节目仍在播放。

用法：python -I tools/verify_switch_stop.py
"""
import os
import sys

os.environ["QSG_RENDER_LOOP"] = "basic"

from PySide6.QtCore import QSettings, QTimer, QUrl               # noqa: E402
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


from hgservice import HgService                        # noqa: E402
from mpv_player import MpvPlayer                       # noqa: E402
from video_item import VideoItem, bind_player          # noqa: E402

QQuickStyle.setStyle("Basic")
app = QApplication(sys.argv)
app.setOrganizationName("IHaveApple")
app.setApplicationName("IHaveApple-switch-stop")
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
QQmlExpression(engine.contextForObject(win), win, "Store.muted = true").evaluate()   # 测试默认静音（Store 要在窗口的上下文里才能解析，根上下文里找不到）
backend.load_async()
STAGE = win.findChild(QQuickItem, "stage")


def ev(obj, expr):
    e = QQmlExpression(engine.contextForObject(obj), obj, expr)
    v = e.evaluate()
    if e.hasError():
        log(f"    {expr}  ERR {e.error().toString()}")
    return v[0] if isinstance(v, tuple) else v


def wait_playing(timeout=40):
    for _ in range(int(timeout * 5)):
        if ev(STAGE, "phase") == "playing":
            return True
        QTest.qWait(200)
    return False


def seek_old():
    """把当前节目拉到 30s，确认确实在播（刚起播时 mpv 还不能 seek，先等一下）"""
    QTest.qWait(1500)
    ev(STAGE, "seekTo(30)")
    QTest.qWait(1200)
    pos = player._get_float("time-pos") or 0
    log(f"  旧节目位置 {pos:.1f}s，暂停={player.paused}")
    return pos


def watch_loading(label):
    """新节目加载期间采样：旧节目的位置还在 = 没停"""
    leaked, samples = [], 0
    for _ in range(80):              # 最多 4s
        QTest.qWait(50)
        if ev(STAGE, "incoming") != -1:   # 切集动画中，旧画面还在滑走，不算
            continue
        if ev(STAGE, "phase") != "loading":
            break
        samples += 1
        pos = player._get_float("time-pos")
        if pos is not None and pos >= 25 and not player.paused:
            leaked.append(round(pos, 1))
    log(f"  加载期采样 {samples} 次，旧节目仍在播的次数 {len(leaked)} {leaked[:5]}")
    check(not leaked, label)


st = {}


def step1():
    log("\n=== 准备：起播 ===")
    check(wait_playing(), "首集已起播")
    st["page"] = ev(win, "player")
    QTimer.singleShot(200, step2)


def step2():
    log("\n=== 1. 滚轮换剧：旧剧立即停止 ===")
    page = st["page"]
    seek_old()
    drama = str(ev(page, "dramaId"))
    ev(page, "onWheel(1)")
    watch_loading("换剧时旧剧已停止")
    check(wait_playing(), "新剧起播")
    check(str(ev(page, "dramaId")) != drama, "确实换了剧")
    QTimer.singleShot(200, step3)


def step3():
    log("\n=== 2. 全剧界面翻集：旧集立即停止 ===")
    page = st["page"]
    ev(page, "enterDramaView()")
    seek_old()
    ep = int(ev(page, "currentEp"))
    ev(page, "onWheel(1)")
    watch_loading("换集时旧集已停止")
    check(wait_playing(), "新集起播")
    check(int(ev(page, "currentEp")) == ep + 1, "确实翻到下一集")
    QTimer.singleShot(200, step4)


def step4():
    log("\n=== 3. 搜索 / 历史选剧：旧剧立即停止 ===")
    page = st["page"]
    ids = ev(win, "Backend.feedIds")
    cur = str(ev(page, "dramaId"))
    target = next((str(i) for i in ids if str(i) != cur), None)
    seek_old()
    ev(page, f"open('{target}')")
    watch_loading("直接打开另一部剧时旧剧已停止")
    check(wait_playing(), "新剧起播")
    log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
    app.quit()


QTimer.singleShot(14000, step1)
QTimer.singleShot(150000, app.quit)
rc = app.exec()
player.shutdown()
backend.shutdown()
sys.exit(rc if not FAILED else 1)
