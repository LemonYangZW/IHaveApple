"""验收：搜索结果封面 + 点击切剧 + 第 20 集之后的切集。

流程与 main.py 一致（含 load_async），`QSG_RENDER_LOOP=basic` 避免 grabWindow 死锁。
输出 PASS/FAIL 行，便于命令行判读。
"""
import json
import os
import sys
import time

os.environ["QSG_RENDER_LOOP"] = "basic"

from PySide6.QtCore import QPoint, QSettings, Qt, QTimer, QUrl        # noqa: E402
from PySide6.QtGui import QFontDatabase                               # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlRegisterSingletonType, qmlRegisterType  # noqa: E402
from PySide6.QtQuick import QQuickItem                                # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle                      # noqa: E402
from PySide6.QtTest import QTest                                      # noqa: E402
from PySide6.QtWidgets import QApplication                            # noqa: E402

PROTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROTO)
OUT = os.path.join(PROTO, "shots", "diag4")
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
app.setApplicationName("IHaveApple-diag4")
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
for k, v in dict(launchPage="player", launchDrama=1, launchWidth=540, launchHeight=960,
                 launchShot=True, systemReducedMotion=True, nativeAspectResize=False).items():
    ctx.setContextProperty(k, v)
engine.load(QUrl.fromLocalFile(os.path.join(PROTO, "qml", "Main.qml")))
win = engine.rootObjects()[0]
QQmlExpression(engine.contextForObject(win), win, "Store.muted = true").evaluate()   # 测试默认静音
backend.load_async()


def ev(obj, expr):
    e = QQmlExpression(engine.contextForObject(obj), obj, expr)
    v = e.evaluate()
    if e.hasError():
        log(f"    {expr}  ERR {e.error().toString()}")
    if isinstance(v, tuple):        # PySide6 把 (值, 是否 QJSValue) 一起返回
        v = v[0]
    return v


def shot(name):
    ok = win.grabWindow().save(os.path.join(OUT, name))
    log(f"[shot] {name} {ok}")


def click(x, y):
    win.requestActivate()
    QTest.mouseMove(win, QPoint(x, y))
    QTest.qWait(120)
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    QTest.qWait(500)


state = {}


def step1_feed():
    log("\n=== 1. 剧单与封面 ===")
    field = win.findChild(QQuickItem, "searchField")
    state["field"] = field
    state["stage"] = win.findChild(QQuickItem, "stage")
    log("  py dramas:", [(d["id"], bool(d.get("cover"))) for d in backend._dramas])
    # 剧单＝整页 feed（实测 9 部），不再固定 4 部
    feed_len = len(backend._dramas)
    check(feed_len >= 5, "剧单来自整页 feed（上游单页 6–9 部浮动）", f"{feed_len} 部")
    check(ev(field, "MockData.dramas.length") == feed_len, "QML 侧剧单一致",
          f"{ev(field, 'MockData.dramas.length')} vs {feed_len}")
    # 启动只转前 3 张封面，其余打开面板时补齐
    warm = sum(1 for d in backend._dramas if d.get("cover"))
    check(warm >= 3, "启动已转好首屏封面", f"{warm}/{feed_len}")
    state["feed_len"] = feed_len
    QTimer.singleShot(200, step2_search)


def wait_covers(timeout=30.0):
    """等后台封面转码结束。

    注意不能把 cover_tried 当作「完成」：它表示「已排队」，转码线程可能还在跑。
    只有拿到 cover（成功）或 cover_error（服务端拒绝 / 转码失败）才算终态。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        pending = [d for d in backend._dramas
                   if d.get("cover_tried") and not (d.get("cover") or d.get("cover_error"))]
        if backend._dramas and not pending:
            return True
        QTest.qWait(200)
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.processEvents()
    return False


def step2_search():
    log("\n=== 2. 搜索：结果带封面 ===")
    field = state["field"]
    click(310, 20)
    field.setProperty("text", "死考")
    QTest.qWait(9000)          # 防抖 + 检索
    ok = wait_covers()
    shot("1-results.png")
    log("  py dramas:", [(d["id"], d["total"], bool(d.get("cover"))) for d in backend._dramas])
    check(len(backend._dramas) > state.get("feed_len", 4), "搜索结果已并入剧单",
          f"{len(backend._dramas)} 部（搜索前 {state.get('feed_len')}）")
    search_items = [d for d in backend._dramas[state.get("feed_len", 4):]]
    got = sum(1 for d in search_items if d.get("cover"))
    degraded = [d for d in search_items if not d.get("cover")]
    # 服务端拒绝（如 /v1/series 502）导致的缺图不算客户端失败，界面会退回占位渐变
    client_bad = [d for d in degraded if not d.get("cover_error")]
    check(bool(search_items) and not client_bad,
          "搜索结果封面（服务端拒绝的除外）",
          f"{got}/{len(search_items)} 张就绪，服务端拒绝 {len(degraded) - len(client_bad)} 张"
          + (f"，客户端失败 {[d['id'] for d in client_bad]}" if client_bad else ""))
    # 以界面真正展示的顺序为准：搜索结果可能包含同系列多季，顺序与 Python 侧切片未必一致
    ui_results = json.loads(ev(win, "JSON.stringify(library.results)") or "[]")
    log("  UI 列表:", [(r["id"], r.get("title", "")[:12]) for r in ui_results])
    if ui_results:
        state["target"] = str(ui_results[0]["id"])
    QTimer.singleShot(200, step3_pick)


def step3_pick():
    log("\n=== 3. 点击第一条搜索结果 ===")
    stage = state["stage"]
    log("  点击前:", ev(stage, "parent.dramaId"), ev(stage, "drama.id"), ev(stage, "episode"))
    click(120, 160)
    QTest.qWait(9000)
    shot("2-picked.png")
    did = str(ev(stage, "parent.dramaId"))
    sid = str(ev(stage, "drama.id"))
    log("  点击后: dramaId=%r drama.id=%r episode=%r phase=%r dur=%r"
        % (did, sid, ev(stage, "episode"), ev(stage, "phase"), ev(stage, "duration")))
    check(did == str(state.get("target")), "player.dramaId 指向被点的剧",
          f"{did} vs {state.get('target')}")
    check(sid == did, "舞台 drama 与被点的剧一致", sid)
    check(ev(stage, "drama.title").startswith("全球死考"), "标题已是全球经济…死考", str(ev(stage, "drama.title")))
    check(ev(stage, "episode") == 0, "从第 1 集开始")
    check(ev(stage, "phase") == "playing", "已起播", str(ev(stage, "phase")))
    QTimer.singleShot(200, step4_jump)


def step4_jump():
    log("\n=== 4. 跳到第 41 集（原上限 20 集）===")
    stage = state["stage"]
    # 等换剧过渡结束，避免 goTo 撞上动画被忽略
    for _ in range(50):
        if not bool(ev(stage, "animating")):
            break
        QTest.qWait(200)
    ev(stage, "parent.goTo(40)")
    QTest.qWait(11000)
    shot("3-ep41.png")
    log("  episode=%r phase=%r dur=%r" % (ev(stage, "episode"), ev(stage, "phase"), ev(stage, "duration")))
    check(ev(stage, "episode") == 40, "已切到第 41 集", str(ev(stage, "episode")))
    check(ev(stage, "phase") in ("playing", "buffering"), "第 41 集起播", str(ev(stage, "phase")))
    log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
    app.quit()


QTimer.singleShot(14000, step1_feed)
QTimer.singleShot(75000, app.quit)
rc = app.exec()
player.shutdown()
backend.shutdown()
sys.exit(rc if not FAILED else 1)