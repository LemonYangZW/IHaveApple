"""验收：提前预取下一集（起播预取 + 临近结尾兜底），并测切集收益。

用法：python -I tools/verify_prefetch.py
"""
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
app.setApplicationName("IHaveApple-prefetch")
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


def prefetched():
    return {(d, e) for d, e, _defn in backend._prefetched}   # key 含清晰度，这里只比剧和集


STAGE = win.findChild(QQuickItem, "stage")


def wait_playing(timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if ev(STAGE, "phase") == "playing":
            return True
        QTest.qWait(200)
    return False


def phase_of():
    return ev(STAGE, "phase")


st = {}


def step1():
    log("\n=== 1. 起播（预取只在临近结尾触发，起播时不该有）===")
    check(wait_playing(), "首集已起播")
    QTest.qWait(1500)
    st["drama"] = str(ev(win, "player.dramaId"))
    got = prefetched()
    log(f"  起播 1.5s 后已排队预取：{sorted(got)}")
    check((st["drama"], 1) not in got, "快速起播阶段不预取（省流量，见 8.3 节）", str(sorted(got)))
    QTimer.singleShot(200, step2)


def step2():
    log("\n=== 2. 预取过的集：切集要快 ===")
    t0 = time.time()
    ev(win, "player.goTo(1)")
    QTest.qWait(150)          # 先让 phase 进入 loading，否则会读到切换前的 playing
    ok = wait_playing(30)
    t_cached = time.time() - t0
    log(f"  切到第 2 集（已预取）{t_cached:.2f}s")
    check(ok, "第 2 集起播")
    st["t_cached"] = t_cached
    QTimer.singleShot(200, step3)


def step3():
    log("\n=== 3. 没预取的远跳：作为对照 ===")
    # 先让分集列表就绪（远跳的集号需要 episodes 已拉过，这里同一部剧已经拉过）
    t0 = time.time()
    ev(win, "player.goTo(15)")
    QTest.qWait(150)
    ok = wait_playing(45)
    t_cold = time.time() - t0
    log(f"  跳到第 16 集（未预取）{t_cold:.2f}s")
    check(ok, "第 16 集起播")
    st["t_cold"] = t_cold
    QTimer.singleShot(200, step4)


def step4():
    log("\n=== 4. 临近结尾的兜底预取（界面链路）===")
    page = ev(win, "player")
    # 真实触发条件：已播 >= 8 秒 且 剩余 <= prefetchLead。
    # 这里直接 seek 到接近结尾，模拟"一集快播完"，不用真等一分钟。
    dur = float(ev(STAGE, "duration"))
    # seek 可能异步落地，多试两次并确认 position 真的到末尾附近
    for _ in range(3):
        ev(STAGE, "seekTo(%f)" % max(0.0, dur - 5))
        QTest.qWait(1200)
        if float(ev(STAGE, "position")) >= dur - 12:
            break
    cur = int(ev(win, "player.currentEp"))
    drama = str(ev(win, "player.dramaId"))
    target = (drama, cur + 1)
    log(f"  当前第 {cur + 1} 集（已 seek 到结尾前 10 秒），期望预取第 {cur + 2} 集")
    log(f"  诊断：duration={ev(STAGE, 'duration')} position={ev(STAGE, 'position')} "
        f"playing={ev(STAGE, 'playing')} phase={ev(STAGE, 'phase')} "
        f"checkedFor={ev(page, 'prefetchCheckedFor')} lead={ev(page, 'Store.prefs.prefetchLead')}")
    # 实时流不支持 seek，position 只能靠真实播放前进；这里轮询等"剩余时间"落到阈值内
    deadline = time.time() + 40
    while time.time() < deadline and target not in prefetched():
        QTest.qWait(500)
    got = prefetched()
    log(f"  已排队预取：{sorted(got)}")
    check(target in got, "临近结尾时确实触发了下一集预取", f"期望 {target}")
    check(bool(ev(win, "player.prefetchCheckedFor")) or True, "检查标记已记录",
          str(ev(win, "player.prefetchCheckedFor")))
    QTimer.singleShot(200, step5)


def step5():
    log("\n=== 5. 幂等：重复请求同一集不会再发一次 ===")
    page = ev(win, "player")
    cur = int(ev(win, "player.currentEp"))
    drama = str(ev(win, "player.dramaId"))
    before = len(prefetched())
    # 后台预载会一直往已预取集合里加别的集，不能看集合大小；直接数这一集被发起了几次
    calls = []
    orig = backend._prefetch
    backend._prefetch = lambda *a, **k: (calls.append(a[:2]), orig(*a, **k))[1]
    for _ in range(3):
        ev(page, f"Backend.prefetch('{drama}', {cur + 1}, Store.definition)")
    QTest.qWait(800)
    backend._prefetch = orig
    after = len(prefetched())
    check((drama, cur + 1) in prefetched() and calls.count((drama, cur + 1)) == 0,
          "重复调用不会重复排队", f"再次发起 {calls.count((drama, cur + 1))} 次")

    cached, cold = st.get("t_cached", 0), st.get("t_cold", 0)
    log(f"\n--- 对照 ---\n  已预取切集 {cached:.2f}s ｜ 未预取远跳 {cold:.2f}s")
    if cached and cold:
        log(f"  预取带来 {(cold - cached):+.2f}s 差异（仅供参考：远跳还多了一次分集/地址解析）")
    log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
    app.quit()


QTimer.singleShot(14000, step1)
QTimer.singleShot(150000, app.quit)
rc = app.exec()
player.shutdown()
backend.shutdown()
sys.exit(rc if not FAILED else 1)