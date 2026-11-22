"""验收：全剧界面——点底部「进入查看全剧」进入本剧的播放界面：
视频不中断、接着当前进度播，顶部换成「返回 + 剧名 + 集数」，滚轮变成翻本剧上下集；返回后滚轮恢复换剧。

用法：python -I tools/verify_album_mode.py
"""
import os
import sys

os.environ["QSG_RENDER_LOOP"] = "basic"

from PySide6.QtCore import QPointF, QSettings, QTimer, QUrl     # noqa: E402
from PySide6.QtGui import QFontDatabase                          # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlRegisterSingletonType, qmlRegisterType  # noqa: E402
from PySide6.QtQuick import QQuickItem                           # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle                 # noqa: E402
from PySide6.QtTest import QTest                                 # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

PROTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROTO)
OUT = os.path.join(PROTO, "shots", "album")
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
app.setApplicationName("IHaveApple-album")
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


def shot(name):
    log(f"[shot] {name} {win.grabWindow().save(os.path.join(OUT, name))}")


def click_item(item):
    c = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    win.requestActivate()
    QTest.mouseMove(win, c.toPoint())
    QTest.qWait(120)
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, c.toPoint())
    QTest.qWait(500)


def wait_playing(timeout=40):
    for _ in range(int(timeout * 5)):
        if ev(STAGE, "phase") == "playing":
            return True
        QTest.qWait(200)
    return False


from PySide6.QtCore import Qt  # noqa: E402

st = {}


def step1():
    log("\n=== 准备：起播 ===")
    check(wait_playing(), "首集已起播")
    QTest.qWait(1000)
    st["page"] = ev(win, "player")
    st["drama"] = str(ev(win, "player.dramaId"))
    st["ep"] = int(ev(win, "player.currentEp"))
    log(f"  {st['drama']} 第 {st['ep'] + 1} 集")
    QTimer.singleShot(200, step2)


def step2():
    log("\n=== 1. 点「进入查看全剧」→ 进入全剧界面，接着当前进度播 ===")
    page = st["page"]
    btn = win.findChild(QQuickItem, "showAllButton")
    check(btn is not None, "底部按钮存在")
    ep_before = int(ev(page, "currentEp"))
    pos_before = float(ev(STAGE, "position"))
    click_item(btn)
    QTest.qWait(900)
    shot("1-drama-view.png")
    check(bool(ev(page, "dramaMode")), "进入本剧模式", str(ev(page, "dramaMode")))
    check(win.findChild(QQuickItem, "episodePage") is None, "不再弹出盖住画面的集号整页")
    ep_after = int(ev(page, "currentEp"))
    pos_after = float(ev(STAGE, "position"))
    log(f"  第 {ep_before + 1} 集 {pos_before:.1f}s → 第 {ep_after + 1} 集 {pos_after:.1f}s，phase={ev(STAGE, 'phase')}")
    check(ep_after == ep_before, "仍是同一集")
    check(pos_after >= pos_before, "进度延续（没有从头播）", f"{pos_before:.1f} → {pos_after:.1f}")
    check(ev(STAGE, "phase") == "playing" and bool(ev(STAGE, "playing")), "视频继续播放")
    ev(STAGE, "wake()")
    QTest.qWait(400)
    bar = win.findChild(QQuickItem, "dramaBar")
    chan = win.findChild(QQuickItem, "channelBar")
    check(bar is not None and bool(bar.isVisible()), "顶部显示全剧栏")
    check(chan is not None and not bool(chan.isVisible()), "频道 tab 让位")
    check(not bool(btn.isVisible()), "「进入查看全剧」入口隐藏")
    QTimer.singleShot(200, step3)


def step3():
    log("\n=== 2. 全剧界面滚轮 = 翻本剧集数 ===")
    page = st["page"]
    ep_before = int(ev(page, "currentEp"))
    drama_before = str(ev(page, "dramaId"))
    c = STAGE.mapToScene(QPointF(STAGE.width() / 2, STAGE.height() / 2)).toPoint()
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QWheelEvent
    e = QWheelEvent(QPointF(c), QPointF(win.mapToGlobal(c)), QPoint(0, 0), QPoint(0, -120),
                    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    app.sendEvent(win, e)
    QTest.qWait(3500)
    ep_after = int(ev(page, "currentEp"))
    drama_after = str(ev(page, "dramaId"))
    log(f"  第 {ep_before + 1} 集 → 第 {ep_after + 1} 集，剧未变={drama_after == drama_before}")
    check(ep_after == ep_before + 1, "真实滚轮翻到下一集", f"{ep_before + 1} → {ep_after + 1}")
    check(drama_after == drama_before, "没有换剧")
    ev(page, "stepEpisodeOrDrama(-1)")
    QTest.qWait(3500)
    check(int(ev(page, "currentEp")) == ep_before, "↑ 翻回上一集", str(int(ev(page, "currentEp")) + 1))
    shot("2-next-ep.png")
    QTimer.singleShot(200, step3b)


def step3b():
    log("\n=== 2b. 第一集 / 最后一集拦截，不换剧 ===")
    page = st["page"]
    drama = str(ev(page, "dramaId"))
    total = int(ev(page, "drama.total"))
    check(int(ev(page, "currentEp")) == 0, "当前在第 1 集")
    ev(page, "stepEpisodeOrDrama(-1)")
    QTest.qWait(1500)
    check(str(ev(page, "dramaId")) == drama and int(ev(page, "currentEp")) == 0,
          "第 1 集往上滚被拦住", f"第 {int(ev(page, 'currentEp')) + 1} 集")
    check(bool(ev(page, "dramaMode")), "仍在全剧界面")
    ev(page, f"goTo({total - 1})")
    QTest.qWait(3500)
    check(int(ev(page, "currentEp")) == total - 1, "跳到最后一集", str(int(ev(page, "currentEp")) + 1))
    ev(page, "onWheel(1)")
    QTest.qWait(1500)
    check(str(ev(page, "dramaId")) == drama and int(ev(page, "currentEp")) == total - 1,
          "最后一集往下滚被拦住", f"第 {int(ev(page, 'currentEp')) + 1} 集")
    check(bool(ev(page, "dramaMode")), "仍在全剧界面")
    shot("2b-last-ep.png")
    QTimer.singleShot(200, step4)


def step4():
    log("\n=== 3. 点返回 → 回到信息流，滚轮换剧 ===")
    page = st["page"]
    ev(STAGE, "wake()")
    QTest.qWait(300)
    back = win.findChild(QQuickItem, "dramaBarBack")
    check(back is not None, "返回按钮存在")
    click_item(back)
    QTest.qWait(600)
    check(not bool(ev(page, "dramaMode")), "已退出本剧模式")
    chan = win.findChild(QQuickItem, "channelBar")
    check(bool(chan.isVisible()), "频道 tab 恢复")
    drama_before = str(ev(page, "dramaId"))
    ev(page, "onWheel(1)")
    QTest.qWait(3500)
    drama_after = str(ev(page, "dramaId"))
    log(f"  剧 {drama_before} → {drama_after}")
    check(drama_after != drama_before, "回到信息流后滚轮换剧")
    shot("3-feed.png")
    QTimer.singleShot(200, step5)


def step5():
    log("\n=== 4. Esc 也能退出全剧界面 ===")
    page = st["page"]
    ev(page, "enterDramaView()")
    QTest.qWait(300)
    check(bool(ev(page, "dramaMode")), "再次进入")
    ev(page, "handleEscape()")
    QTest.qWait(300)
    check(not bool(ev(page, "dramaMode")), "Esc 退出全剧界面")
    log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
    app.quit()


QTimer.singleShot(14000, step1)
QTimer.singleShot(120000, app.quit)
rc = app.exec()
player.shutdown()
backend.shutdown()
sys.exit(rc if not FAILED else 1)