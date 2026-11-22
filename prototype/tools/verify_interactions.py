"""交互验证：模拟按键 / 点击，在关键时刻截图。仅用于开发自查。

用法：python -I tools/verify_interactions.py <prototype 目录> <输出目录>
"""
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QMetaObject, QSettings, QPoint, QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import QFontDatabase, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

PROTO = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(PROTO))   # native_window.py
OUT = Path(sys.argv[2]).resolve()
OUT.mkdir(parents=True, exist_ok=True)

QQuickStyle.setStyle("Basic")
app = QApplication(sys.argv)
app.setOrganizationName("IHaveApple")
app.setApplicationName("IHaveApple-verify")   # 独立的设置存储，每次清空
QSettings().clear()
for f in (PROTO / "fonts").glob("*.ttf"):
    QFontDatabase.addApplicationFont(str(f))

engine = QQmlApplicationEngine()
ctx = engine.rootContext()
for k, v in dict(launchPage="player", launchDrama=1, launchWidth=0, launchHeight=0,
                 launchShot=True, systemReducedMotion=False, nativeAspectResize=False).items():
    ctx.setContextProperty(k, v)
engine.load(QUrl.fromLocalFile(str(PROTO / "qml" / "Main.qml")))
win = engine.rootObjects()[0]
QQmlExpression(engine.contextForObject(win), win, "Store.muted = true").evaluate()   # 测试默认静音

steps = []
def at(ms, fn): steps.append((ms, fn))
def shot(name): return lambda: print(name, win.grabWindow().save(str(OUT / f"{name}.png")))
def key(k, mod=Qt.NoModifier):
    def run():
        win.requestActivate()          # 其他窗口抢走焦点时 Shortcut 不会触发
        QTest.keyClick(win, k, mod)
    return run
def resize(w, h): return lambda: win.resize(w, h)
_hover = [0]
def hover_stage():
    def run():
        # 每次换一个位置：移到同一坐标不会产生移动事件，控件不会被唤醒
        _hover[0] = (_hover[0] + 1) % 2
        win.requestActivate()
        QTest.mouseMove(win, QPoint(win.width() // 2 + _hover[0] * 20, win.height() // 2))
    return run

def click(object_name):
    def run():
        item = win.findChild(QQuickItem, object_name)
        p = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        win.requestActivate()
        QTest.mouseClick(win, Qt.LeftButton, Qt.NoModifier, p)
    return run

def report(tag): return lambda: print(tag, f"{win.x()},{win.y()} {win.width()}x{win.height()}", f"ratio={win.width() / win.height():.4f}")

# 0. 默认窗口：控件可见 → 鼠标静止 3 秒后只剩视频
at(300, report("default-size"))
at(400, hover_stage())
at(800, shot("i0a-chrome"))
at(3700, shot("i0b-idle"))
# 1. 上一集：切集动画中途 + 字幕卡
at(4500, key(Qt.Key_Up))
at(4640, shot("i1-reel-mid"))
at(5000, shot("i2-titlecard"))
# 2. 倍速快捷键 → toast
at(6200, key(Qt.Key_BracketRight))
at(6500, shot("i3-speed-toast"))
# 3. 点「选集」按钮打开面板 → 下一集（选框与视频联动）
at(7000, hover_stage())
at(7100, click("episodesButton"))
at(7500, shot("i4-episode-sheet"))
at(7600, key(Qt.Key_Down))
at(7740, shot("i5-sheet-reel-mid"))
at(8300, key(Qt.Key_Escape))
# 4. 倍速菜单
at(8600, hover_stage())
at(8700, click("speedButton"))
at(9000, shot("i6-speed-menu"))
at(9100, key(Qt.Key_Escape))
# 5. 窄窗口 + 选集面板
at(9400, resize(480, 800))
at(9700, hover_stage())
at(9800, key(Qt.Key_E))
at(10200, shot("i7-narrow-sheet"))
at(10300, key(Qt.Key_Escape))
# 6. 演示面板
at(10600, key(Qt.Key_D, Qt.ControlModifier | Qt.ShiftModifier))
at(11000, shot("i8-demo-panel"))
# 7. 按比例缩放：直接调用 resizeLocked（合成的鼠标拖拽一旦移出窗口就会丢失释放事件，不可靠）
def qml(expr): return lambda: QQmlExpression(QQmlEngine.contextForObject(win), win, expr).evaluate()
at(11300, key(Qt.Key_Escape))
at(11500, resize(540, 960))
at(11700, report("before-drag"))
at(11800, qml("resizeLocked(Qt.RightEdge, Qt.rect(x, y, width, height), 120, 0)"))
at(12000, report("after-right+120"))
at(12100, qml("resizeLocked(Qt.TopEdge, Qt.rect(x, y, width, height), 0, 200)"))
at(12300, report("after-top-200"))
at(12400, qml("resizeLocked(Qt.LeftEdge | Qt.BottomEdge, Qt.rect(x, y, width, height), -30, 300)"))
at(12600, report("after-corner"))
at(12700, qml("resizeLocked(Qt.BottomEdge, Qt.rect(x, y, width, height), 0, -900)"))
at(12900, report("after-min-clamp"))
# 8. 适应屏幕高度 → 还原
at(13000, qml("toggleFit()"))
at(13300, report("fitted"))
at(13300, shot("i9-fitted"))
at(13400, qml("toggleFit()"))
at(13700, report("restored"))
# 9. 搜索：输入（空格、E 不触发播放快捷键）→ 无结果 → 回车切剧；观看历史
def type_text(t):
    # QTest.keyClicks 只支持 QWidget；QQuickWindow 直接发送带文本的按键事件（也能输入中文）
    def run():
        win.requestActivate()
        for ch in t:
            k = Qt.Key_Space if ch == " " else Qt.Key_E if ch == "E" else 0
            for typ in (QEvent.KeyPress, QEvent.KeyRelease):
                QGuiApplication.sendEvent(win, QKeyEvent(typ, k, Qt.NoModifier, ch))
    return run
def state(tag):
    expr = "'drama=' + player.dramaId + ' ep=' + (player.currentEp + 1) + ' episodes=' + player.episodesOpen + ' library=' + library.mode"
    return lambda: print(tag, QQmlExpression(QQmlEngine.contextForObject(win), win, expr).evaluate()[0],
                         "playing=" + str(win.findChild(QQuickItem, "stage").property("playing")))
at(13800, resize(540, 960))
at(14000, key(Qt.Key_F, Qt.ControlModifier))
at(14300, shot("j1-search-empty"))
at(14400, type_text("E xyz"))
at(14700, shot("j2-search-none"))
at(14800, state("after-typing"))
at(14900, key(Qt.Key_A, Qt.ControlModifier))
at(15000, type_text("总裁"))
at(15300, shot("j3-search-result"))
at(15400, key(Qt.Key_Return))
at(15800, state("after-enter"))
at(16000, hover_stage())
at(16100, click("historyButton"))
at(16500, shot("j4-history"))
at(16600, key(Qt.Key_E))
at(16900, state("after-E"))
at(17000, resize(360, 640))
at(17100, click("historyButton"))
at(17500, shot("j5-history-narrow"))
# 10. 设置页：改键（含冲突）、最小化暂停、滚轮调音量、窗口置顶、关闭自动连播
def ev(tag, expr):
    return lambda: print(tag, QQmlExpression(QQmlEngine.contextForObject(win), win, expr).evaluate()[0])
def find_item(name, root=None):
    # Repeater 生成的项不在 QObject 树上，findChild 找不到，按可视项树查找
    for it in (root or win.contentItem()).childItems():
        if it.objectName() == name:
            return it
        found = find_item(name, it)
        if found:
            return found
    return None
def press_cap(action):
    return lambda: QMetaObject.invokeMethod(find_item("key_" + action), "click")
def stage_set(name, expr):
    def run():
        st = win.findChild(QQuickItem, "stage")
        st.setProperty(name, expr(st))
    return run
KEYS = "'episodes=' + Store.keys.episodes + ' fullscreen=' + Store.keys.fullscreen"
at(18000, key(Qt.Key_Escape))
at(18050, resize(540, 960))
at(18100, hover_stage())
at(18200, click("settingsButton"))
at(18500, shot("k1-settings"))
at(18600, press_cap("episodes"))
at(18700, key(Qt.Key_G))
at(18800, ev("rebind-G", KEYS))
at(18900, press_cap("episodes"))
at(19000, key(Qt.Key_F))
at(19100, ev("conflict-F", KEYS))
at(19200, key(Qt.Key_Escape))
at(19300, ev("esc-closes-settings", "'settings.open=' + settings.open"))
at(19400, key(Qt.Key_F))
at(19600, ev("F-opens-episodes", "'episodes=' + player.episodesOpen + ' immersive=' + win.immersive"))
at(19700, key(Qt.Key_Escape))
at(19800, ev("reset", "Store.resetKeys(), " + KEYS))
at(19900, lambda: win.showMinimized())
at(20300, state("minimized"))
at(20400, lambda: win.showNormal())
at(20800, state("restored"))
at(20900, ev("wheel-volume", "Store.volume = 0.8, Store.prefs.wheelAction = 'volume', player.onWheel(-1), 'volume=' + Store.volume"))
at(21000, ev("wheel-reset", "Store.prefs.wheelAction = 'episode'"))
at(21100, ev("on-top", "Store.prefs.alwaysOnTop = true, ''"))
at(21400, ev("on-top-flags", "'onTop=' + ((win.flags & Qt.WindowStaysOnTopHint) !== 0) + ' visible=' + win.visible"))
at(21500, ev("on-top-off", "Store.prefs.alwaysOnTop = false, ''"))
at(21600, ev("auto-next-off", "Store.prefs.autoNext = false, ''"))
at(21650, stage_set("playing", lambda st: True))
at(21700, stage_set("position", lambda st: st.property("duration") - 0.3))
at(22300, state("held-at-end"))
at(22350, shot("k2-held-at-end"))
at(22400, ev("auto-next-on", "Store.prefs.autoNext = true, ''"))
at(22500, resize(360, 640))
at(22600, ev("settings-narrow", "settings.show(), ''"))
at(23000, shot("k3-settings-narrow"))
# 11. 关闭到托盘：关闭 → 隐藏并暂停 → 从托盘恢复 → 继续播放（预先标记提示已显示，避免弹出系统通知）
at(23100, resize(540, 960))
at(23200, ev("tray-on", "settings.close(), Store.prefs.trayHintShown = true, Store.prefs.closeAction = 'tray', "
              "'available=' + tray.available + ' trayVisible=' + tray.visible"))
at(23300, stage_set("position", lambda st: 1.0))
at(23310, stage_set("playing", lambda st: True))
at(23400, lambda: win.close())
at(23700, lambda: print("closed-to-tray", "visible=" + str(win.isVisible()),
                        "playing=" + str(win.findChild(QQuickItem, "stage").property("playing"))))
at(23800, ev("show-from-tray", "showFromTray(), ''"))
at(24200, lambda: print("restored-from-tray", "visible=" + str(win.isVisible()),
                        "playing=" + str(win.findChild(QQuickItem, "stage").property("playing"))))
at(24300, ev("tray-off", "Store.prefs.closeAction = 'quit', 'trayVisible=' + tray.visible"))
# 12. 原生等比缩放：给窗口发送 WM_SIZING（拖右边到 660 宽），检查过滤器是否把高度修正为 9:16
def wm_sizing():
    import ctypes
    from ctypes import wintypes
    from native_window import install_aspect_resize, WMSZ_RIGHT, WM_SIZING
    global _filter
    _filter = install_aspect_resize(win, 9 / 16, 640)
    rc = wintypes.RECT(100, 100, 760, 1060)
    ctypes.windll.user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]
    ctypes.windll.user32.SendMessageW(int(win.winId()), WM_SIZING, WMSZ_RIGHT, ctypes.addressof(rc))
    print("wm-sizing", rc.right - rc.left, "x", rc.bottom - rc.top)
at(24400, wm_sizing)
at(24800, app.quit)

# 默认的粗粒度计时器在长延时下误差约 5%，会打乱步骤顺序，所以用精确计时器
timers = []
for ms, fn in steps:
    t = QTimer(singleShot=True, timerType=Qt.PreciseTimer)
    t.timeout.connect(fn)
    t.start(ms)
    timers.append(t)
sys.exit(app.exec())
