"""验收：滚动换短剧 + 底部「查看全集」横幅 + 看完一集自动连播同一部。

用法：python -I tools/verify_feed_scroll.py
"""
import json
import os
import sys

os.environ["QSG_RENDER_LOOP"] = "basic"

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl          # noqa: E402
from PySide6.QtGui import QFontDatabase                          # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlRegisterSingletonType  # noqa: E402
from PySide6.QtQuick import QQuickItem                           # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle                 # noqa: E402
from PySide6.QtTest import QTest                                 # noqa: E402
from PySide6.QtWidgets import QApplication                       # noqa: E402

PROTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROTO)
OUT = os.path.join(PROTO, "shots", "feed_scroll")
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
from video_item import install_video          # noqa: E402

QQuickStyle.setStyle("Basic")
app = QApplication(sys.argv)
app.setOrganizationName("IHaveApple")
app.setApplicationName("IHaveApple-scroll")
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


def ev(obj, expr):
    e = QQmlExpression(engine.contextForObject(obj), obj, expr)
    v = e.evaluate()
    if e.hasError():
        log(f"    {expr}  ERR {e.error().toString()}")
    return v[0] if isinstance(v, tuple) else v


def shot(name):
    log(f"[shot] {name} {win.grabWindow().save(os.path.join(OUT, name))}")


def drama_id():
    return str(ev(win, "player.dramaId"))


def feed_ids():
    return [str(i) for i in (ev(win, "Backend.feedIds") or [])]


st = {}


def step1_banner():
    log("\n=== 1. 底部信息区（剧名 + 简介 + 集数 + 查看全集）===")
    banner = win.findChild(QQuickItem, "dramaInfo")
    st["banner"] = banner
    st["page"] = ev(win, "player")
    check(banner is not None, "信息区已实例化")
    check(bool(ev(banner, "hasContent")), "信息区有内容")
    title = str(ev(banner, "title"))
    desc = str(ev(banner, "desc"))
    total = ev(banner, "total")
    log(f"  剧名：{title}")
    log(f"  简介：{desc[:40]}…")
    log(f"  集数：第 {ev(banner, 'episode')} 集 / 共 {total} 集")
    check(title != "" and title != "正在载入…", "显示当前剧名", title)
    check(desc != "", "显示简介", f"{len(desc)} 字")
    check(int(total or 0) > 0, "显示总集数", str(total))
    # 标题栏不再显示剧名（搬到底部了）
    check(win.findChild(QQuickItem, "dramaTitle") is not None, "剧名 Label 在信息区里")
    btn = win.findChild(QQuickItem, "showAllButton")
    check(btn is not None, "「查看全集」按钮存在")
    st["drama0"] = drama_id()
    st["ids0"] = feed_ids()
    check(len(st["ids0"]) >= 5, "频道剧单可用于滚动", f"{len(st['ids0'])} 部")
    shot("1-banner.png")
    QTimer.singleShot(200, step2_show_all)


def step2_show_all():
    log("\n=== 2. 点「查看全集」→ 选集面板 ===")
    ev(win, "player.toggleEpisodes()")      # 横幅点击等价于这个
    QTest.qWait(900)
    shot("2-episodes.png")
    open_sheet = bool(ev(win, "player.episodesOpen"))
    check(open_sheet, "选集面板已打开", str(open_sheet))
    ev(win, "player.closeEpisodes()")
    QTest.qWait(500)
    check(not bool(ev(win, "player.episodesOpen")), "可以再关上")
    QTimer.singleShot(200, step3_scroll)


def step3_scroll():
    log("\n=== 3. 滚动 = 换一部短剧（信息流模式）===")
    # 上一步打开过选集面板 → 处于本剧模式。这里先退出，验证信息流语义。
    ev(st["page"], "dramaMode = false")
    before = drama_id()
    ep_before = ev(win, "player.currentEp")
    # 与滚轮等价的入口：PlayerPage.onWheel(1)
    ev(st["page"], "onWheel(1)")
    QTest.qWait(3500)
    after = drama_id()
    log(f"  {before} → {after}（集号 {ep_before} → {ev(win, 'player.currentEp')}）")
    check(after != before, "滚动换到了另一部剧", f"{before} → {after}")
    check(after in st["ids0"], "新剧在同一频道的剧单里", after)
    check(int(ev(win, "player.currentEp")) == 0, "换剧从第 1 集开始",
          str(ev(win, "player.currentEp")))
    shot("3-scrolled.png")
    st["drama1"] = after
    QTimer.singleShot(200, step4_scroll_back)


def step4_scroll_back():
    log("\n=== 4. 反向滚动回到上一部 ===")
    ev(st["page"], "onWheel(-1)")
    QTest.qWait(3500)
    back = drama_id()
    log(f"  {st['drama1']} → {back}")
    check(back == st["drama0"], "反着滚回到原来那部", f"{back} vs {st['drama0']}")
    QTimer.singleShot(200, step5_autoplay)


def step5_autoplay():
    log("\n=== 5. 一集播完 → 自动进入本剧下一集（不换剧）===")
    before = drama_id()
    ep_before = int(ev(win, "player.currentEp"))
    total = int(ev(win, "player.drama.total"))
    log(f"  当前 {before} 第 {ep_before + 1}/{total} 集，模拟本集播完")
    ev(st["page"], "onEpisodeFinished()")
    QTest.qWait(4000)
    after = drama_id()
    ep_after = int(ev(win, "player.currentEp"))
    log(f"  → {after} 第 {ep_after + 1} 集")
    check(after == before, "没有换剧（仍是同一部）", f"{after} vs {before}")
    check(ep_after == ep_before + 1, "自动进入了下一集", f"{ep_before + 1} → {ep_after + 1}")
    shot("4-autoplay.png")
    log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
    app.quit()


QTimer.singleShot(15000, step1_banner)
QTimer.singleShot(120000, app.quit)
rc = app.exec()
player.shutdown()
backend.shutdown()
sys.exit(rc if not FAILED else 1)