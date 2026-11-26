"""验收：播放中改静音 / 音量 / 倍速 / 清晰度，立即作用到正在播的这一集。

  · 音量、静音、倍速：改完 0.3s 内 mpv 对应属性已变（之前只在装载下一集时才下发）
  · 倍速：2 秒墙钟时间内播放位置前进约 2 × 倍速
  · 清晰度：mpv 改播新清晰度的地址（本集已缓存为 1080p 也要能换，SDK 用 strict=1），
    从原位置接着播；暂停中切换仍保持暂停；落在同一路流（自动 → 1080P）时不重载

全程静音（先把音量设为 0 再测静音开关，不会出声）。
用法：python -I tools/verify_live_settings.py
"""
import ctypes as C
import os
import sys

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


import mpv_player as mp                                # noqa: E402
from hgservice import HgService, video_cache_dir             # noqa: E402
from mpv_player import MpvPlayer                       # noqa: E402
from video_item import install_video          # noqa: E402

mp._lib.mpv_get_property_string.argtypes = [C.c_void_p, C.c_char_p]
mp._lib.mpv_get_property_string.restype = C.c_void_p
mp._lib.mpv_free.argtypes = [C.c_void_p]

QQuickStyle.setStyle("Basic")
app = QApplication(sys.argv)
app.setOrganizationName("IHaveApple")
app.setApplicationName("IHaveApple-live-settings")
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
# 测试默认静音（Store 要在窗口的上下文里才能解析，根上下文里找不到）
QQmlExpression(engine.contextForObject(win), win, "Store.muted = true").evaluate()
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


def mpv_str(name):
    p = mp._lib.mpv_get_property_string(player._handle, name.encode())
    if not p:
        return ""
    try:
        return C.string_at(p).decode("utf-8", "replace")
    finally:
        mp._lib.mpv_free(p)


def pos():
    return player._get_float("time-pos") or 0.0


def wait_until(fn, timeout):
    for _ in range(int(timeout * 10)):
        if fn():
            return True
        QTest.qWait(100)
    return False


def episode_ids():
    drama = str(ev("dramaId", PAGE))
    return [e["id"] for e in backend._episodes.get(drama, [])]


def is_cached(eid):
    return any(f.startswith(eid + "_") for f in os.listdir(video_cache_dir()))


def step1():
    global PAGE
    log("\n=== 准备：起播 ===")
    check(wait_until(lambda: ev("phase") == "playing", 40), "首集已起播")
    PAGE = ev("player", win)
    QTest.qWait(1500)
    check(player._get_flag("mute") is True, "起播时静音已下发")

    log("\n=== 1. 音量 / 静音 ===")
    ev("Store.volume = 0")
    QTest.qWait(300)
    check(player._get_float("volume") == 0, "音量实时生效", f"volume={player._get_float('volume')}")
    ev("Store.muted = false")           # 音量为 0，取消静音也不会出声
    QTest.qWait(300)
    check(player._get_flag("mute") is False, "取消静音实时生效")
    ev("Store.muted = true")
    QTest.qWait(300)
    check(player._get_flag("mute") is True, "静音实时生效")
    ev("Store.volume = 0.8")
    QTest.qWait(300)
    check(abs((player._get_float("volume") or 0) - 80) < 1, "音量恢复实时生效")

    log("\n=== 2. 倍速 ===")
    ev("Store.speed = 2.0")
    QTest.qWait(300)
    check(player._get_float("speed") == 2.0, "倍速属性实时生效", f"speed={player._get_float('speed')}")
    a = pos()
    QTest.qWait(2000)
    adv = pos() - a
    check(3.2 <= adv <= 4.8, "2× 时 2 秒前进约 4 秒", f"前进 {adv:.2f}s")
    ev("Store.speed = 1.0")
    QTest.qWait(300)
    check(player._get_float("speed") == 1.0, "倍速恢复 1×")
    QTimer.singleShot(100, step2)


def step2():
    ids = episode_ids()
    cur = int(ev("currentEp", PAGE))
    # 起播几秒后 SDK 就会把这一集落盘为 1080p；换清晰度要用 strict 绕开「缓存优先」
    log(f"\n本集已缓存：{bool(ids) and is_cached(ids[cur])}")

    log("\n=== 3. 清晰度：自动 → 1080P（实际是同一路流，不应重载） ===")
    old_path = mpv_str("path")
    ev("Store.quality = '1080P'")
    ok = wait_until(lambda: not ev("switching") and ev("activeQuality") == "1080P", 30)
    QTest.qWait(800)
    check(ok, "切换请求已处理")
    check(mpv_str("path").replace("&strict=1", "") == old_path.replace("&strict=1", ""), "同一路流不重载")

    log("\n=== 4. 清晰度（播放中） ===")
    switch_quality("720P", "720p")
    check(ev("phase") == "playing" and ev("playing") is True and not player.paused, "切换后仍在播放")

    log("\n=== 5. 清晰度（暂停中） ===")
    ev("togglePlay()")
    QTest.qWait(500)
    before, _, after = switch_quality("480P", "480p")
    check(player.paused and ev("playing") is False, "暂停中切换后仍保持暂停")
    check(abs(after - before) < 1.5, "暂停中切换位置不变", f"{before:.1f}s → {after:.1f}s")
    finish()


def switch_quality(label, defn):
    """切换清晰度；返回 (切换前位置, 新地址装入前一刻的位置, 切换后位置)"""
    old_path = mpv_str("path")
    before = pos()
    last = [before]
    ev(f"Store.quality = '{label}'")

    def arrived():
        if f"definition={defn}" in mpv_str("path"):
            return not ev("switching")
        last[0] = pos()          # 新地址装入前，原画面一直在播
        return False
    ok = wait_until(arrived, 45)
    QTest.qWait(800)
    after = pos()
    log(f"  旧地址 …{old_path[-40:]}\n  新地址 …{mpv_str('path')[-40:]}")
    check(ok, f"已切到 {label} 的地址")
    check(ev("activeQuality") == label, f"activeQuality = {label}", str(ev("activeQuality")))
    check(after >= last[0] - 0.5, f"切到 {label} 后从当前位置接着播（不回跳）",
          f"发起时 {before:.1f}s，装入前 {last[0]:.1f}s → 切换后 {after:.1f}s")
    return before, last[0], after


def finish():
    log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
    app.quit()


QTimer.singleShot(14000, step1)
QTimer.singleShot(170000, app.quit)
rc = app.exec()
player.shutdown()
backend.shutdown()
sys.exit(rc if not FAILED else 1)
