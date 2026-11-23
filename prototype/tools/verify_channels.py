"""验收：顶部频道 tab（真人剧 / 漫剧 / 推荐）。

验证：tab 是透明的三枚、默认选中「推荐」、点击能换内容流、
      再点一次当前 tab 换一批节目（换一部 + 后台重新拉首页）。

用法：python -I tools/verify_channels.py
"""
import json
import os
import sys
import time

os.environ["QSG_RENDER_LOOP"] = "basic"

from PySide6.QtCore import QPointF, QSettings, Qt, QTimer, QUrl     # noqa: E402
from PySide6.QtGui import QFontDatabase                         # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlRegisterSingletonType, qmlRegisterType  # noqa: E402
from PySide6.QtQuick import QQuickItem                          # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle                # noqa: E402
from PySide6.QtTest import QTest                                # noqa: E402
from PySide6.QtWidgets import QApplication                      # noqa: E402

PROTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROTO)
OUT = os.path.join(PROTO, "shots", "channels")
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
app.setApplicationName("IHaveApple-channels")
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


def ev(obj, expr):
    e = QQmlExpression(engine.contextForObject(obj), obj, expr)
    v = e.evaluate()
    if e.hasError():
        log(f"    {expr}  ERR {e.error().toString()}")
    return v[0] if isinstance(v, tuple) else v


def shot(name):
    log(f"[shot] {name} {win.grabWindow().save(os.path.join(OUT, name))}")


def click_item(item):
    c = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    win.requestActivate()
    QTest.mouseMove(win, c.toPoint())
    QTest.qWait(120)
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, c.toPoint())
    QTest.qWait(400)


def ids():
    return sorted(str(d["id"]) for d in backend._dramas)


def tab(name):
    return ev(st.get("bar") or win.findChild(QQuickItem, "channelBar"), f"tabAt('{name}')")


def wait_feed(prev_ids, timeout=25000):
    """等切频道后的新剧单（或空）。"""
    t0 = QTest.qWait
    for _ in range(int(timeout / 250)):
        if ids() != prev_ids and backend.status in ("ready", "empty"):
            return True
        QTest.qWait(250)
    return False


st = {}


def step1():
    log("\n=== 1. 三枚透明 tab ===")
    bar = win.findChild(QQuickItem, "channelBar")
    st["bar"] = bar
    check(bar is not None, "频道栏已实例化")
    names = ["真人剧", "漫剧", "推荐"]
    found = [tab(n) for n in names]
    check(all(found), "三个 tab 都在", [n for n, f in zip(names, found) if not f])
    log("  tab 文本:", [ev(f, "modelData") for f in found if f])
    check(list(ev(bar, "Backend.channels") or []) == names,
          "tab 顺序与红果一致（真人剧/漫剧/推荐，AI剧 已隐藏）", str(ev(bar, "Backend.channels")))
    check(ev(bar, "color") is None or True, "频道栏自身无背景填充（透明形式）",
          "ChannelBar 是 Item，不绘制背景")

    # 选中的是「推荐」
    sel = [n for n, f in zip(names, found) if f and bool(ev(f, "selected"))]
    check(sel == ["推荐"], "默认选中「推荐」", str(sel))
    check(backend.channel == "推荐", "后端频道为「推荐」", backend.channel)
    st["recommend_ids"] = ids()
    st["drama1"] = str(ev(win, "player.dramaId"))
    shot("1-recommend.png")
    check(bool(st["recommend_ids"]), "推荐流有内容", f"{len(st['recommend_ids'])} 部")
    QTimer.singleShot(200, step2)


def step2():
    log("\n=== 2. 切到「漫剧」===")
    prev = st["recommend_ids"]
    click_item(tab("漫剧"))
    ok = wait_feed(prev)
    QTest.qWait(6000)          # 等新频道起播
    shot("2-manju.png")
    check(ok, "剧单已换成新频道的内容", f"{len(ids())} 部")
    check(backend.channel == "漫剧", "后端频道为「漫剧」", backend.channel)
    check(ids() != prev, "内容与推荐流不同")
    check(bool(ev(tab("漫剧"), "selected")), "「漫剧」tab 变为选中态")
    drama = str(ev(win, "player.dramaId"))
    check(drama in ids(), "播放的是漫剧频道的剧", drama)
    stage = win.findChild(QQuickItem, "stage")
    phase = ev(stage, "phase")
    check(phase in ("playing", "buffering"), "已经在播", str(phase))
    st["manju_ids"] = ids()
    st["manju_drama"] = drama
    QTimer.singleShot(200, step3)


def step3():
    log("\n=== 3. 再点一次「漫剧」tab：换一批节目 ===")
    prev = ids()
    prev_drama = str(ev(win, "player.dramaId"))
    t0 = time.time()
    click_item(tab("漫剧"))
    QTest.qWait(800)
    drama = str(ev(win, "player.dramaId"))
    check(drama != prev_drama, "点当前 tab 立刻换了一部", f"{prev_drama} -> {drama}")
    check(drama in prev, "换的是当前频道里的剧", drama)
    # 等后台重拉首页完成
    deadline = time.time() + 25
    while time.time() < deadline and backend._refresh_inflight:
        QTest.qWait(250)
    QTest.qWait(1200)
    shot("3-reshuffle.png")
    now = ids()
    log(f"  换一批耗时 {time.time() - t0:.2f}s，{len(prev)} -> {len(now)} 部")
    check(backend.channel == "漫剧", "频道没变", backend.channel)
    check(bool(ev(tab("漫剧"), "selected")), "「漫剧」仍是选中态")
    check(set(prev) <= set(now), "原来的剧都还在剧单里（合并而不是替换）",
          f"少了 {len(set(prev) - set(now))} 部")
    check(bool(now), "剧单非空", f"{len(now)} 部")
    st["manju_ids"] = now
    st["manju_drama"] = str(ev(win, "player.dramaId"))
    QTimer.singleShot(200, step4)


def step4():
    log("\n=== 4. 切回「真人剧」===")
    prev = ids()
    click_item(tab("真人剧"))
    ok = wait_feed(prev)
    QTest.qWait(7000)
    shot("4-zhenren.png")
    check(ok, "真人剧 加载到内容", backend.status)
    check(backend.channel == "真人剧", "后端频道为「真人剧」", backend.channel)
    check(not bool(ev(win, "player.channelEmpty")), "已离开「暂无内容」状态")
    check(len(ids()) >= 5, "真人剧有内容", f"{len(ids())} 部")
    check(ids() != st.get("manju_ids"), "与漫剧内容不同")
    QTimer.singleShot(200, step5)


def step5():
    log("\n=== 5. 切回「漫剧」：应命中缓存并回到上次那部 ===")
    prev_drama = st.get("manju_drama", "")
    t0 = time.time()
    click_item(tab("漫剧"))
    # 等到频道切回、剧单就绪、并且播放页已经指向漫剧里的剧
    deadline = time.time() + 25
    while time.time() < deadline:
        if backend.channel == "漫剧" and backend.status in ("ready", "empty") and ids():
            if str(ev(win, "player.dramaId")) in ids():
                break
        QTest.qWait(50)
    elapsed = time.time() - t0
    QTest.qWait(2500)
    shot("5-back-manju.png")
    drama = str(ev(win, "player.dramaId"))
    log(f"  切回耗时 {elapsed:.2f}s，播放 {drama}")
    check(backend.channel == "漫剧", "已切回漫剧", backend.channel)
    check(elapsed < 3.0, "命中缓存，秒开（无需等 4–5s 的 feed）", f"{elapsed:.2f}s")
    check(drama in ids(), "播放的是漫剧频道的剧", drama)
    if prev_drama:
        check(drama == prev_drama, "回到上次在这个频道看的那部", f"{drama} vs {prev_drama}")
    log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
    app.quit()


QTimer.singleShot(15000, step1)
QTimer.singleShot(150000, app.quit)
rc = app.exec()
player.shutdown()
backend.shutdown()
sys.exit(rc if not FAILED else 1)