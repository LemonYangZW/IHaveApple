"""验收：搜索 / 历史是整版页面（铺满窗口、能显示更多结果），并验证开关时的暂停恢复。

用法：python -I tools/verify_search_page.py
"""
import json
import os
import sys
import time

os.environ["QSG_RENDER_LOOP"] = "basic"

from PySide6.QtCore import QSettings, QTimer, QUrl              # noqa: E402
from PySide6.QtGui import QFontDatabase                          # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlRegisterSingletonType, qmlRegisterType  # noqa: E402
from PySide6.QtQuick import QQuickItem                           # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle                 # noqa: E402
from PySide6.QtTest import QTest                                 # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

PROTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROTO)
OUT = os.path.join(PROTO, "shots", "search_page")
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
app.setApplicationName("IHaveApple-searchpage")
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


def shot(name):
    log(f"[shot] {name} {win.grabWindow().save(os.path.join(OUT, name))}")


def wait_playing(timeout=40):
    for _ in range(int(timeout * 5)):
        if ev(STAGE, "phase") == "playing":
            return True
        QTest.qWait(200)
    return False


st = {}


def step1():
    log("\n=== 准备：起播 ===")
    check(wait_playing(), "首集已起播")
    QTest.qWait(800)
    st["playing"] = bool(ev(win, "player.playing"))
    check(st["playing"], "播放中", str(st["playing"]))
    QTimer.singleShot(200, step2)


def step2():
    log("\n=== 1. 打开搜索：整版页面 ===")
    lib = win.findChild(QQuickItem, "libraryPanel")
    st["lib"] = lib
    check(lib is not None, "搜索页面已实例化")
    ev(win, "library.show('search')")
    QTest.qWait(900)
    h = float(ev(lib, "height"))
    y = float(ev(lib, "y"))
    log(f"  页面 y={y:.0f} height={h:.0f}，窗口 {win.height()}")
    check(abs(y + h - win.height()) < 2, "页面铺到窗口底部（整版）", f"{y + h:.0f} vs {win.height()}")
    check(h > win.height() * 0.85, "高度占窗口 85% 以上", f"{h / win.height() * 100:.0f}%")
    QTimer.singleShot(200, step3)


def step3():
    log("\n=== 2. 整页打开时视频暂停 ===")
    QTest.qWait(500)
    playing = bool(ev(win, "player.playing"))
    log(f"  playing={playing}")
    check(not playing, "整页盖住画面后暂停播放", str(playing))
    QTimer.singleShot(200, step4)


def step4():
    log("\n=== 3. 搜索并等待封面 ===")
    lib = st["lib"]
    field = win.findChild(QQuickItem, "searchField")
    check(field is not None, "搜索框存在")
    field.setProperty("text", "死考")
    t0 = time.time()
    # 等搜索结果和封面（最多 20 秒）
    deadline = time.time() + 20
    results_n = 0
    covers = 0
    while time.time() < deadline:
        results_n = len(json.loads(ev(lib, "JSON.stringify(results)") or "[]"))
        if results_n:
            result_ids = {str(r["id"]) for r in json.loads(ev(lib, "JSON.stringify(results)") or "[]")}
            covers = sum(1 for d in (backend._dramas or [])
                         if str(d["id"]) in result_ids and d.get("cover"))
            if covers >= results_n - 1:      # 允许一条服务端 502 的
                break
        QTest.qWait(200)
    elapsed = time.time() - t0
    log(f"  {results_n} 条结果，{covers} 张封面就绪，用时 {elapsed:.1f}s")
    shot("1-search-page.png")
    check(results_n > 0, "搜索有结果", str(results_n))
    check(covers >= max(1, results_n - 1), "封面基本加载出来", f"{covers}/{results_n}")
    # 列表能显示的行数（整页应比原来 70% 高度多）
    listview = win.findChild(QQuickItem, "searchList")
    if listview is not None:
        log(f"  列表高度 {float(ev(listview, 'height')):.0f}")
    QTimer.singleShot(200, step5)


def step5():
    log("\n=== 4. 关闭后恢复播放 ===")
    ev(win, "library.close()")
    QTest.qWait(1200)
    playing = bool(ev(win, "player.playing"))
    log(f"  playing={playing}")
    check(playing, "关闭整页后恢复播放", str(playing))
    shot("2-closed.png")
    log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
    app.quit()


QTimer.singleShot(14000, step1)
QTimer.singleShot(120000, app.quit)
rc = app.exec()
player.shutdown()
backend.shutdown()
sys.exit(rc if not FAILED else 1)