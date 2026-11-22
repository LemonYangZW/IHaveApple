"""验收：暂停时的中央播放按钮 + 工具栏「窗口适配视频比例」按钮。

用法：python -I tools/verify_ui_actions.py
输出 PASS/FAIL，退出码 0 表示全通过。
"""
import os
import sys

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
OUT = os.path.join(PROTO, "shots", "ui_actions")
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
app.setApplicationName("IHaveApple-ui")
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

# 帧计数：用于验证「暂停且无交互时不重绘」（设计文档第 10 节）
frames = [0]
win.frameSwapped.connect(lambda: frames.__setitem__(0, frames[0] + 1))


def ev(obj, expr):
    e = QQmlExpression(engine.contextForObject(obj), obj, expr)
    v = e.evaluate()
    if e.hasError():
        log(f"    {expr}  ERR {e.error().toString()}")
    return v[0] if isinstance(v, tuple) else v


def shot(name):
    log(f"[shot] {name} {win.grabWindow().save(os.path.join(OUT, name))}")


def Player_w():
    return player.videoWidth


def Player_h():
    return player.videoHeight


def click_item(item, dx=None, dy=None):
    """按窗口坐标点击控件中心（控件通常嵌在 Row/Item 里，x/y 是相对父项的）。"""
    from PySide6.QtCore import QPointF
    c = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    log(f"  点击 {item.objectName()} @ ({c.x():.0f}, {c.y():.0f})")
    click(int(c.x()), int(c.y()))


def click(x, y):
    win.requestActivate()
    QTest.mouseMove(win, QPoint(x, y))
    QTest.qWait(120)
    QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    QTest.qWait(500)


st = {}


def step1_pause():
    log("\n=== 1. 暂停时的中央播放按钮 ===")
    st["stage"] = win.findChild(QQuickItem, "stage")
    st["page"] = ev(win, "player")
    btn = win.findChild(QQuickItem, "centerPlayButton")
    st["btn"] = btn
    check(btn is not None, "中央播放按钮已实例化")
    log("  起播状态: phase=%r playing=%r" % (ev(st["stage"], "phase"), ev(st["stage"], "playing")))
    check(ev(btn, "visible") in (False, 0), "播放中不显示", str(ev(btn, "visible")))

    ev(st["page"], "togglePlay()")          # 暂停
    QTest.qWait(700)
    shot("1-paused.png")
    log("  暂停后: phase=%r playing=%r visible=%r opacity=%r"
        % (ev(st["stage"], "phase"), ev(st["stage"], "playing"),
           ev(btn, "visible"), ev(btn, "opacity")))
    check(ev(st["stage"], "playing") in (False, 0), "已暂停")
    check(ev(btn, "visible") in (True, 1), "暂停后按钮显示")
    check(float(ev(btn, "opacity")) > 0.5, "按钮不透明度已到位", str(ev(btn, "opacity")))
    # 半透明底：颜色 alpha < 1
    alpha = ev(btn, "color.a")
    check(float(alpha) < 1.0, "按钮底色是半透明（能透出画面）", f"alpha={alpha}")

    # 设计文档第 10 节：暂停且没有交互时窗口 MUST NOT 重绘。
    # 中央按钮只用一次性淡入，不能留循环动画。
    frames[0] = 0
    QTest.qWait(2000)
    check(frames[0] <= 6, "暂停且无交互时几乎不重绘", f"2 秒内 {frames[0]} 帧")
    QTimer.singleShot(200, step2_click_center)


def step2_click_center():
    log("\n=== 2. 点中央按钮继续播放 ===")
    b = st["btn"]
    click_item(b)
    QTest.qWait(1200)
    log("  点击后: playing=%r visible=%r" % (ev(st["stage"], "playing"), ev(b, "visible")))
    check(ev(st["stage"], "playing") in (True, 1), "点按钮恢复播放")
    check(ev(b, "visible") in (False, 0), "恢复播放后按钮隐藏")
    QTimer.singleShot(200, step3_fit)


def step3_fit():
    log("\n=== 3. 工具栏「窗口适配视频比例」 ===")
    page = st["page"]
    before_w, before_h = win.width(), win.height()
    foot = win.findChild(QQuickItem, "fitVideoButton")
    check(foot is not None, "工具栏按钮已实例化")
    log("  当前窗口 %dx%d 比例 %.3f" % (before_w, before_h, before_w / before_h))
    log("  视频尺寸 %dx%d 比例 %.3f"
        % (Player_w(), Player_h(), ev(win, "win.videoAspect")))

    # 先切到横屏片源，才能看出「适配」前后的差异
    backend.search("死考")
    QTest.qWait(4000)
    wide = [d for d in backend._dramas if str(d["total"]) == "785"]
    if wide:
        ev(page, f"open('{wide[0]['id']}')")
        QTest.qWait(9000)
    vw, vh = Player_w(), Player_h()
    log("  切入后视频尺寸 %dx%d 比例 %.3f" % (vw, vh, ev(win, "win.videoAspect")))
    check(abs(float(ev(win, "win.windowAspect")) - 9 / 16) < 0.01,
          "默认仍是 9:16 锁定", str(ev(win, "win.windowAspect")))

    click_item(foot)
    QTest.qWait(1200)
    shot("2-fitted.png")
    w, h = win.width(), win.height()
    ratio = w / h
    want = float(ev(win, "win.videoAspect"))
    log("  适配后窗口 %dx%d 比例 %.3f（视频 %.3f）" % (w, h, ratio, want))
    check(bool(ev(win, "win.fitToVideo")), "开关已打开")
    check(abs(ratio - want) < 0.02, "窗口比例 ≈ 视频比例", f"{ratio:.3f} vs {want:.3f}")
    check(bool(ev(foot, "active")), "按钮显示为选中态")
    QTimer.singleShot(200, step4_restore)


def step4_restore():
    log("\n=== 4. 再点一次恢复 9:16 ===")
    foot = win.findChild(QQuickItem, "fitVideoButton")
    click_item(foot)
    QTest.qWait(1200)
    shot("3-restored.png")
    w, h = win.width(), win.height()
    log("  恢复后窗口 %dx%d 比例 %.3f" % (w, h, w / h))
    check(not bool(ev(win, "win.fitToVideo")), "开关已关闭")
    check(abs(w / h - 9 / 16) < 0.02, "窗口回到 9:16", f"{w / h:.3f}")
    log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
    app.quit()


QTimer.singleShot(15000, step1_pause)
QTimer.singleShot(90000, app.quit)
rc = app.exec()
player.shutdown()
backend.shutdown()
sys.exit(rc if not FAILED else 1)