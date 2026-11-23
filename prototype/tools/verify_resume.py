"""验收：从观看历史续播时，真的从上次的位置起播（之前只把进度条设到那里，播放器仍从 0 秒开始）。

  · 已落盘的集：直接从记录的位置起播
  · 没落盘的集：本地 SDK 给的是实时流、不能 seek，后端先等落盘（几秒）再给地址，仍从记录的位置起播
  · 进度条（stage.position）与播放器位置一致

全程静音。用法：python -I tools/verify_resume.py
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
RESUME = 30.0


def log(*a):
    print(*a, flush=True)


def check(cond, label, detail=""):
    log(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILED.append(label)


from hgservice import HgService, video_cache_dir             # noqa: E402
from mpv_player import MpvPlayer                       # noqa: E402
from video_item import VideoItem, bind_player          # noqa: E402

QQuickStyle.setStyle("Basic")
app = QApplication(sys.argv)
app.setOrganizationName("IHaveApple")
app.setApplicationName("IHaveApple-resume")
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
    return any(f.startswith(eid + "_") for f in os.listdir(video_cache_dir()))


def resume(ep, label):
    """把这一集的观看进度记为 RESUME 秒，从另一部剧切回来（同观看历史里选剧），看实际从哪里起播。
    open() 会先保存「当前」剧的进度，所以要先切走，再写进度，否则写的进度会被覆盖。"""
    drama = str(ev("dramaId", PAGE))
    other = next(str(i) for i in ev("Backend.feedIds", win) if str(i) != drama)
    ev(f"open('{other}')", PAGE)
    QTest.qWait(500)
    ev(f"Store.saveProgress('{drama}', {ep}, {RESUME})", PAGE)
    ev(f"open('{drama}')", PAGE)
    ok = wait_until(lambda: ev("phase") == "playing" and pos() > 0, 45)
    QTest.qWait(600)
    p, ui = pos(), float(ev("position"))
    check(ok, f"{label}：已起播")
    check(int(ev("currentEp", PAGE)) == ep, f"{label}：打开的是记录的那一集", f"第 {int(ev('currentEp', PAGE)) + 1} 集")
    check(RESUME - 0.5 <= p <= RESUME + 3, f"{label}：从 {RESUME:.0f}s 起播", f"播放器位置 {p:.1f}s")
    check(abs(ui - p) < 1.5, f"{label}：进度条与播放器一致", f"进度条 {ui:.1f}s")


def step1():
    global PAGE
    log("\n=== 准备：起播 ===")
    check(wait_until(lambda: ev("phase") == "playing", 40), "首集已起播")
    PAGE = ev("player", win)
    QTest.qWait(3000)               # 开播几秒后 SDK 会把这一集落盘
    drama = str(ev("dramaId", PAGE))
    ids = [e["id"] for e in backend._episodes.get(drama, [])]
    cur = int(ev("currentEp", PAGE))

    log("\n=== 1. 续播已落盘的集 ===")
    check(is_cached(ids[cur]), "当前集已落盘")
    resume(cur, "已落盘")

    log("\n=== 2. 续播没落盘的集 ===")
    target = next((i for i in range(cur + 1, len(ids)) if not is_cached(ids[i])), -1)
    check(target >= 0, "找到没落盘的集", str(target))
    if target >= 0:
        resume(target, "没落盘")

    log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
    app.quit()


QTimer.singleShot(14000, step1)
QTimer.singleShot(170000, app.quit)
rc = app.exec()
player.shutdown()
backend.shutdown()
sys.exit(rc if not FAILED else 1)
