"""验收：提前预载往上拖会依次看到的 5 个节目，翻过去基本无缝。

  · 信息流：当前剧起播后，剧单接下来 5 部（各自要起播的那一集）依次落盘，越近越先好
  · 翻到下一部：直接读落盘的文件 —— 起播快、一上来就能 seek
  · 本剧模式：接下来 5 集落盘
  · 位置变了重排队列：翻过去后，新的「接下来 5 个」也会补上

全程静音。用法：python -I tools/verify_preload.py
"""
import os
import sys
import time

os.environ["QSG_RENDER_LOOP"] = "basic"

from PySide6.QtCore import QSettings, QTimer, QUrl               # noqa: E402
from PySide6.QtGui import QFontDatabase                          # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlRegisterSingletonType  # noqa: E402
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


from hgservice import HgService, video_cache_dir             # noqa: E402
from mpv_player import MpvPlayer                       # noqa: E402
from video_item import install_video          # noqa: E402

QQuickStyle.setStyle("Basic")
app = QApplication(sys.argv)
app.setOrganizationName("IHaveApple")
app.setApplicationName("IHaveApple-preload")
QSettings().clear()
for f in os.listdir(os.path.join(PROTO, "fonts")):
    if f.endswith(".ttf"):
        QFontDatabase.addApplicationFont(os.path.join(PROTO, "fonts", f))

player, backend = MpvPlayer(), HgService()
app._p, app._b = player, backend
qmlRegisterSingletonType(MpvPlayer, "IHaveApple", 1, 0, "Player", lambda _e: player)
qmlRegisterSingletonType(HgService, "IHaveApple", 1, 0, "Backend", lambda _e: backend)

engine = QQmlApplicationEngine()
install_video(engine, player)
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


def eid_of(drama, ep):
    eps = backend._episodes.get(drama) or []
    return eps[ep]["id"] if 0 <= ep < len(eps) else ""


def is_cached(drama, ep):
    eid = eid_of(drama, ep)
    return bool(eid) and any(f.startswith(eid + "_") for f in os.listdir(video_cache_dir()))


def expected_feed(n=5):
    """播放页算出的「接下来 n 部」：(dramaId, 起播集)"""
    out, cur = [], str(ev("dramaId", PAGE))
    for _ in range(n):
        cur = str(ev(f"neighborId(1, '{cur}')", PAGE))
        if not cur or cur == str(ev("dramaId", PAGE)):
            break
        out.append((cur, int(ev(f"startOf('{cur}').ep", PAGE))))
    return out


def wait_cached(items, timeout, label):
    t0, done = time.time(), {}

    def all_done():
        for it in items:
            if it not in done and is_cached(*it):
                done[it] = time.time() - t0
        return len(done) == len(items)
    ok = wait_until(all_done, timeout)
    log("  " + "，".join(f"{d[-4:]}#{e + 1}:{done[(d, e)]:.0f}s" if (d, e) in done else f"{d[-4:]}#{e + 1}:—"
                        for d, e in items))
    check(ok, label, f"{len(done)}/{len(items)}")
    return done


def step1():
    global PAGE
    check(wait_until(lambda: ev("phase") == "playing", 40), "首集已起播")
    PAGE = ev("player", win)
    ids = [str(i) for i in ev("Backend.feedIds", win)]
    log(f"剧单 {len(ids)} 部")

    log("\n=== 1. 信息流：接下来 5 部依次落盘 ===")
    items = expected_feed()
    check(len(items) == min(5, len(ids) - 1), "算出接下来 5 部", str(len(items)))
    wait_cached(items, 120, "接下来 5 部都已落盘")

    log("\n=== 2. 翻到下一部：读落盘文件，起播快、能 seek ===")
    nxt = items[0][0]
    t0 = time.time()
    ev("onSwipe(1)", PAGE)
    ok = wait_until(lambda: str(ev("dramaId", PAGE)) == nxt and ev("phase") == "playing", 20)
    dt = time.time() - t0
    check(ok, "翻到下一部并起播", f"{dt:.1f}s")
    check(dt < 2.5, "起播快（不等实时转封装）", f"{dt:.1f}s")
    check(bool(player.seekable), "一上来就是可 seek 的文件（读的是落盘缓存）")

    log("\n=== 3. 翻过去后补上新的「接下来 5 部」 ===")
    items2 = expected_feed()
    wait_cached(items2, 90, "新的接下来 5 部也已落盘")

    log("\n=== 4. 本剧模式：接下来 5 集 ===")
    ev("enterDramaView()", PAGE)
    drama, cur = str(ev("dramaId", PAGE)), int(ev("currentEp", PAGE))
    total = int(ev("drama.total", PAGE))
    eps = [(drama, cur + k) for k in range(1, 6) if cur + k < total]
    wait_cached(eps, 120, "本剧接下来 5 集都已落盘")
    finish()


def finish():
    log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
    app.quit()


QTimer.singleShot(14000, step1)
QTimer.singleShot(420000, app.quit)
rc = app.exec()
player.shutdown()
backend.shutdown()
sys.exit(rc if not FAILED else 1)
