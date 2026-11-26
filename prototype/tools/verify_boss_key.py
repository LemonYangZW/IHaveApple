"""验收：一键隐藏（全局快捷键）。

覆盖：
  1. 按键序列解析：组合键、单键、F 键、方向键、符号键（需要 Shift 的补 Shift）、认不出的返回 None
  2. 系统级注册：注册成功；同一个键再注册一次失败（模拟被其他程序占用）；清空后可以重新注册
  3. 模拟按键（SendInput）触发 WM_HOTKEY → activated
  4. 播放器里：按一次窗口、任务栏按钮、托盘图标都藏起来；再按一次恢复；改键后旧键失效、新键生效

不联网、不启动片源服务。用法：python tools/verify_boss_key.py
"""
import ctypes
import os
import sys
from ctypes import wintypes

os.environ["QSG_RENDER_LOOP"] = "basic"

from PySide6.QtCore import QSettings, QUrl                          # noqa: E402
from PySide6.QtGui import QFontDatabase                             # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlRegisterSingletonType  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle                    # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

PROTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROTO)
FAILED = []


def log(*a):
    print(*a, flush=True)


def check(cond, label, detail=""):
    log(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILED.append(label)


from native_window import (MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT,  # noqa: E402
                           GlobalHotkey, parse_sequence)

# ---------- 1. 解析 ----------
log("=== 1. 按键序列解析 ===")
N = MOD_NOREPEAT
check(parse_sequence("Ctrl+Alt+H") == (N | MOD_CONTROL | MOD_ALT, ord("H")), "Ctrl+Alt+H")
check(parse_sequence("H") == (N, ord("H")), "单键 H")
check(parse_sequence("F9") == (N, 0x78), "单键 F9")
check(parse_sequence("Shift+F12") == (N | MOD_SHIFT, 0x7B), "Shift+F12")
check(parse_sequence("Ctrl+Down") == (N | MOD_CONTROL, 0x28), "Ctrl+Down")
check(parse_sequence("Alt+5") == (N | MOD_ALT, ord("5")), "Alt+5")
check(parse_sequence("`", vk_scan=lambda c: 0xC0) == (N, 0xC0), "符号键 `")
check(parse_sequence("{", vk_scan=lambda c: 0x1DB) == (N | MOD_SHIFT, 0xDB), "需要 Shift 的符号补 Shift")
check(parse_sequence("Ctrl++", vk_scan=lambda c: 0x1BB) == (N | MOD_CONTROL | MOD_SHIFT, 0xBB), "Ctrl + 加号")
check(parse_sequence("") is None and parse_sequence("Meta+X") is None and parse_sequence("F25") is None,
      "空 / 认不出的修饰键 / 不存在的键返回 None")

# ---------- 准备 Qt ----------
QQuickStyle.setStyle("Basic")
app = QApplication(sys.argv[:1])
app.setOrganizationName("IHaveApple")
app.setApplicationName("IHaveApple-bosskey")
QSettings().clear()
for f in os.listdir(os.path.join(PROTO, "fonts")):
    if f.endswith(".ttf"):
        QFontDatabase.addApplicationFont(os.path.join(PROTO, "fonts", f))

# 选一个几乎不会被占用的组合当测试键
SEQ = "Ctrl+Alt+Shift+F11"
SEQ2 = "Ctrl+Alt+Shift+F10"


class _KI(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KI), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def press(seq):
    """用 SendInput 按下再松开整组键（系统级，和真人按键一样会触发全局热键）。"""
    mods, vk = parse_sequence(seq)
    keys = [k for f, k in ((MOD_CONTROL, 0x11), (MOD_ALT, 0x12), (MOD_SHIFT, 0x10)) if mods & f] + [vk]
    seq_in = [(k, 0) for k in keys] + [(k, 2) for k in reversed(keys)]     # 2 = KEYEVENTF_KEYUP
    arr = (_INPUT * len(seq_in))(*[_INPUT(type=1, ki=_KI(wVk=k, dwFlags=fl)) for k, fl in seq_in])
    ctypes.windll.user32.SendInput(len(seq_in), arr, ctypes.sizeof(_INPUT))
    QTest.qWait(400)


# ---------- 2 / 3. 系统级注册 ----------
log("\n=== 2. 系统级注册 ===")
hk = GlobalHotkey()
hits = []
hk.activated.connect(lambda: hits.append(1))
check(hk.setSequence(SEQ) is True, "注册成功", SEQ)
other = GlobalHotkey()
check(other.setSequence(SEQ) is False, "同一个键再注册失败（被占用）")
check(hk.setSequence("") is True and other.setSequence(SEQ) is True, "清空后别人可以注册")
other.shutdown()
check(hk.setSequence(SEQ) is True, "再注册回来")
check(hk.setSequence("Meta+X") is False, "认不出的键注册失败")

log("\n=== 3. 模拟按键触发 ===")
hk.setSequence(SEQ)
press(SEQ)
check(len(hits) == 1, "按下热键触发 activated", str(len(hits)))
hk.shutdown()

# ---------- 4. 播放器里 ----------
log("\n=== 4. 播放器里一键隐藏 ===")
from hgservice import HgService                                   # noqa: E402
from mpv_player import MpvPlayer                                  # noqa: E402
from updater import Updater                                       # noqa: E402
from video_item import install_video                     # noqa: E402

player, backend, updater = MpvPlayer(), HgService(), Updater()
backend._backfill_covers_async = lambda *a, **k: None
hotkey = GlobalHotkey()
app._keep = (player, backend, updater, hotkey)
qmlRegisterSingletonType(MpvPlayer, "IHaveApple", 1, 0, "Player", lambda _e: player)
qmlRegisterSingletonType(HgService, "IHaveApple", 1, 0, "Backend", lambda _e: backend)
qmlRegisterSingletonType(Updater, "IHaveApple", 1, 0, "Updater", lambda _e: updater)
engine = QQmlApplicationEngine()
install_video(engine, player)
WARN = []
engine.warnings.connect(lambda ws: [WARN.append(w.toString()) or log("[qml]", w.toString()) for w in ws])
ctx = engine.rootContext()
for k, v in dict(launchPage="player", launchDrama=0, launchWidth=540, launchHeight=960, launchShot=True,
                 systemReducedMotion=True, nativeAspectResize=False, globalHotkey=hotkey).items():
    ctx.setContextProperty(k, v)
engine.load(QUrl.fromLocalFile(os.path.join(PROTO, "qml", "Main.qml")))
win = engine.rootObjects()[0]


def ev(expr):
    e = QQmlExpression(engine.contextForObject(win), win, expr)
    v = e.evaluate()
    if e.hasError():
        log(f"    {expr}  ERR {e.error().toString()}")
    return v[0] if isinstance(v, tuple) else v


ev("Store.muted = true")
ev("Store.prefs.closeAction = 'tray'")            # 托盘图标显示出来，才测得到「一起藏起来」
ev(f"Store.setKey('bossKey', '{SEQ}')")
QTest.qWait(500)
check(bool(ev("win.visible")) and bool(ev("tray.visible")), "起始：窗口和托盘图标都在")
press(SEQ)
check(ev("win.bossHidden") is True, "按一次：进入隐藏状态")
check(ev("win.visible") is False, "窗口（含任务栏按钮）已隐藏")
check(ev("tray.visible") is False, "托盘图标已隐藏")
press(SEQ)
check(ev("win.bossHidden") is False and ev("win.visible") is True, "再按一次：窗口恢复")
check(ev("tray.visible") is True, "托盘图标恢复")
# 全屏时隐藏，恢复后仍是全屏
ev("win.immersive = true; win.showFullScreen()")
QTest.qWait(300)
press(SEQ)
press(SEQ)
check(ev("win.visibility === Window.FullScreen") is True, "全屏下隐藏再恢复：仍是全屏")
ev("win.setImmersive(false)")
# 改键：旧键失效、新键生效
ev(f"Store.setKey('bossKey', '{SEQ2}')")
press(SEQ)
check(ev("win.bossHidden") is False, "改键后旧键不再触发")
press(SEQ2)
check(ev("win.bossHidden") is True, "新键生效")
press(SEQ2)
check(ev("win.visible") is True, "恢复")
# 清空：不再注册
ev("Store.setKey('bossKey', '')")
press(SEQ2)
check(ev("win.bossHidden") is False, "清空快捷键后不再触发")
check(not [w for w in WARN if "Main.qml" in w or "SettingsPage" in w], "没有 QML 警告", "; ".join(WARN[:3]))

# ---------- 5. 真实播放：隐藏时暂停，恢复后接着播 ----------
log("\n=== 5. 真实播放：隐藏时暂停、恢复后接着播 ===")
ev("Store.prefs.pauseOnMinimize = false")         # 关掉「最小化暂停」，确认暂停是一键隐藏自己做的
ev(f"Store.setKey('bossKey', '{SEQ}')")
backend.load_async()
for _ in range(400):
    if ev("player.playing && Player.position > 1") is True:
        break
    QTest.qWait(100)
check(ev("player.playing") is True, "已起播")
press(SEQ)
check(ev("player.playing") is False, "隐藏时暂停了")
press(SEQ)
check(ev("player.playing") is True, "恢复后接着播")
ev("player.togglePlay()")                          # 手动暂停后隐藏 → 恢复时保持暂停
press(SEQ)
press(SEQ)
check(ev("player.playing") is False, "隐藏前就是暂停的：恢复后保持暂停")

hotkey.shutdown()
player.shutdown()
backend.shutdown()
QSettings().clear()
log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
sys.exit(1 if FAILED else 0)
