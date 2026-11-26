"""验收：观看历史 / 搜索记录跨重启保留，「完全重置」清干净。

覆盖：
  1. 写入：看过的剧（含标题快照）、搜索记录最多 10 条（去重置顶）；搜索框为空时显示最近搜索，点一条重新搜
  2. 重启（新进程）后读回：进度、搜索记录都在；历史里的剧并回剧单，MockData.drama() 能解析到原标题
  3. 换频道后剧单重建，历史里的剧仍然解析得到
  4. 「完全重置」：退出后清掉设置 / 记录（注册表）、缓存目录、更新包，且不会被 QML 写回
  5. 收藏夹：收藏 / 取消、重启后还在、收藏的剧并回剧单；点开续播并进全剧界面；清空历史不丢收藏的进度
  6. 续播判断：时长快照随进度保存；重启后没有剧集信息时不再按 90 秒兜底把「看到一半」误判成看完

不联网、不启动片源服务；LOCALAPPDATA / TEMP 指向临时目录，用独立的应用名，不碰正在用的播放器数据。
用法：python tools/verify_records.py
"""
import os
import subprocess
import sys
import tempfile

PHASE = sys.argv[1] if len(sys.argv) > 1 else "main"
if PHASE == "main":
    SANDBOX = tempfile.mkdtemp(prefix="iha-records-")
else:
    SANDBOX = sys.argv[2]
os.environ["LOCALAPPDATA"] = os.path.join(SANDBOX, "local")
os.environ["TEMP"] = os.environ["TMP"] = os.path.join(SANDBOX, "temp")
os.environ.pop("IHAVEAPPLE_CACHE", None)
os.makedirs(os.environ["TEMP"], exist_ok=True)
os.environ["QSG_RENDER_LOOP"] = "basic"

APP_NAME = "IHaveApple-records"
DRAMA = "7700000000000000001"
FEED = "7700000000000000002"     # 只在信息流里看过
EPS = "7700000000000000003"      # 打开过选集面板
FAV = "7700000000000000004"      # 收藏；这一集时长已知（120 秒），看到 116 秒 = 已看完
LONG = "7700000000000000005"     # 只收藏没进历史；时长未知，看到 100 秒
PROTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROTO)
FAILED = []


def log(*a):
    print(*a, flush=True)


def check(cond, label, detail=""):
    log(("PASS " if cond else "FAIL ") + label + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILED.append(label)


def run_phase(name):
    r = subprocess.run([sys.executable, os.path.abspath(__file__), name, SANDBOX])
    check(r.returncode == 0, f"阶段 {name} 通过")


if PHASE == "main":
    # 每个阶段一个进程：「重启后还在不在」只有换进程才测得准
    from PySide6.QtCore import QCoreApplication, QSettings
    QCoreApplication.setOrganizationName("IHaveApple")
    QCoreApplication.setApplicationName(APP_NAME)
    QSettings().clear()
    for p in ("write", "read", "reset"):
        run_phase(p)
    QSettings().clear()
    subprocess.run(["reg", "delete", rf"HKCU\Software\IHaveApple\{APP_NAME}", "/f"], capture_output=True)
    import shutil
    shutil.rmtree(SANDBOX, ignore_errors=True)
    from PySide6.QtCore import QStandardPaths
    shutil.rmtree(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation), ignore_errors=True)
    log("ALL PASS" if not FAILED else f"FAILED: {FAILED}")
    sys.exit(1 if FAILED else 0)


import shiboken6                                                   # noqa: E402
from PySide6.QtCore import QObject, QSettings, QTimer, QUrl       # noqa: E402
from PySide6.QtGui import QFontDatabase                           # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlRegisterSingletonType  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle                  # noqa: E402
from PySide6.QtWidgets import QApplication                        # noqa: E402

from hgservice import HgService                                   # noqa: E402
from mpv_player import MpvPlayer                                  # noqa: E402
from updater import Updater                                       # noqa: E402
from video_item import install_video                     # noqa: E402

QQuickStyle.setStyle("Basic")
app = QApplication(sys.argv[:1])
app.setOrganizationName("IHaveApple")
app.setApplicationName(APP_NAME)
for f in os.listdir(os.path.join(PROTO, "fonts")):
    if f.endswith(".ttf"):
        QFontDatabase.addApplicationFont(os.path.join(PROTO, "fonts", f))

player, backend, updater = MpvPlayer(), HgService(), Updater()
backend._backfill_covers_async = lambda *a, **k: None   # 不联网补封面
app._keep = (player, backend, updater)
qmlRegisterSingletonType(MpvPlayer, "IHaveApple", 1, 0, "Player", lambda _e: player)
qmlRegisterSingletonType(HgService, "IHaveApple", 1, 0, "Backend", lambda _e: backend)
qmlRegisterSingletonType(Updater, "IHaveApple", 1, 0, "Updater", lambda _e: updater)

WARNINGS = []
engine = QQmlApplicationEngine()
install_video(engine, player)
engine.warnings.connect(lambda ws: [WARNINGS.append(w.toString()) or log("[qml]", w.toString()) for w in ws])
ctx = engine.rootContext()
for k, v in dict(launchPage="player", launchDrama=0, launchWidth=540, launchHeight=960,
                 launchShot=True, systemReducedMotion=True, nativeAspectResize=False).items():
    ctx.setContextProperty(k, v)
engine.load(QUrl.fromLocalFile(os.path.join(PROTO, "qml", "Main.qml")))
win = engine.rootObjects()[0]


def ev(obj, expr):
    e = QQmlExpression(engine.contextForObject(obj), obj, expr)
    v = e.evaluate()
    if e.hasError():
        log(f"    {expr}  ERR {e.error().toString()}")
    return v[0] if isinstance(v, tuple) else v


def settle(ms=200):
    from PySide6.QtTest import QTest
    QTest.qWait(ms)


ev(win, "Store.muted = true")      # 测试默认静音
field = win.findChild(QObject, "searchField")   # 它的上下文里有 lib / field
settle()


def finish():
    shiboken6.delete(engine)       # 让 QML Settings 析构时把值刷进注册表
    QSettings().sync()


if PHASE == "write":
    backend.rememberDramas([{"id": DRAMA, "title": "测试剧", "total": 60, "desc": "简介"},
                            {"id": FEED, "title": "信息流剧", "total": 30, "desc": ""},
                            {"id": EPS, "title": "选集剧", "total": 40, "desc": ""}])
    check(ev(win, f"MockData.drama('{DRAMA}').title") == "测试剧", "rememberDramas 后剧单能解析")
    # 观看历史只收进过全剧界面的剧：信息流里看只记进度
    ev(win, f"player.open('{FEED}')")
    check(ev(win, f"Store.progressOf('{FEED}') !== null") is True, "信息流里看的剧记了进度")
    check(ev(win, "Store.history().length") == 0, "信息流里看的剧不进观看历史")
    ev(win, f"player.open('{DRAMA}')")
    ev(win, "player.enterDramaView()")
    check(ev(win, "Store.history().map(h => h.id).join(',')") == DRAMA, "点「查看全集」后进观看历史",
          ev(win, "Store.history().map(h => h.id).join(',')"))
    ev(win, f"player.open('{EPS}')")
    ev(win, "player.toggleEpisodes()")
    check(ev(win, f"Store.history().some(h => h.id === '{EPS}')") is True, "打开选集面板后也进观看历史")
    ev(win, "player.toggleEpisodes()")
    settle(50)
    ev(win, f"Store.saveProgress('{DRAMA}', 3, 12.5)")
    check(ev(win, f"Store.progressOf('{DRAMA}').listed") is True, "之后保存进度不会把剧移出历史")
    for i in range(12):
        ev(win, f"Store.addSearch('词{i}')")
    ev(win, "Store.addSearch('  词5 ')")       # 重复的词挪到最前面，不重复记
    s = ev(win, "Store.searches.join(',')")
    check(s == "词5,词11,词10,词9,词8,词7,词6,词4,词3,词2", "搜索记录去重置顶、最多 10 条", s)
    ev(win, "Store.addSearch('')")
    check(ev(win, "Store.searches.length") == 10, "空搜索词不记")

    ev(win, "library.show('search')")
    settle(400)
    check(ev(field, "lib.showRecent") is True, "搜索框为空时显示最近搜索")
    ev(field, "lib.searchAgain('词3')")
    check(ev(field, "field.text") == "词3" and ev(win, "Store.searches[0]") == "词3", "点最近搜索：填回搜索框并置顶")
    check(ev(field, "lib.showRecent") is False, "有输入时不显示最近搜索")
    ev(field, "field.text = '回车词'; field.accepted()")
    check(ev(win, "Store.searches[0]") == "回车词", "回车记入搜索记录")
    ev(field, "field.text = ''")
    # 收藏夹
    backend.rememberDramas([{"id": FAV, "title": "收藏剧", "total": 20, "desc": ""},
                            {"id": LONG, "title": "长集剧", "total": 20, "desc": ""}])
    check(ev(win, f"Store.toggleFavorite('{FAV}')") is True, "收藏一部剧")
    check(ev(win, f"Store.toggleFavorite('{LONG}')") is True, "再收藏一部")
    check(ev(win, f"Store.toggleFavorite('{EPS}') && !Store.toggleFavorite('{EPS}')") is True, "收藏后可以取消")
    check(ev(win, "Store.favorites.map(f => f.id).join(',')") == f"{LONG},{FAV}", "收藏夹新收藏的在前",
          ev(win, "Store.favorites.map(f => f.id).join(',')"))
    check(ev(win, "Store.toggleFavorite('7709999999999999999')") is False, "剧单里没有的剧收藏不了")
    # 时长快照：剧集信息里有时长就跟着进度存下来
    backend._episodes[FAV] = [{"id": f"{FAV}-{i}", "duration": 120} for i in range(20)]
    ev(win, f"Store.saveProgress('{FAV}', 5, 116)")
    check(ev(win, f"Store.progressOf('{FAV}').dur") == 120, "进度里记下了这一集的时长",
          ev(win, f"Store.progressOf('{FAV}').dur"))
    ev(win, f"Store.saveProgress('{LONG}', 2, 100)")
    # 控件栏的弹幕开关：和设置页「显示弹幕」是同一项
    btn = win.findChild(QObject, "danmakuButton")
    check(ev(win, "Store.prefs.danmaku") is True and ev(btn, "active") is True, "弹幕默认开启，按钮为选中态")
    ev(btn, "clicked()")
    check(ev(win, "Store.prefs.danmaku") is False and ev(btn, "active") is False, "点弹幕按钮关闭弹幕")
    ev(win, "Store.toggleDanmaku()")
    check(ev(win, "Store.prefs.danmaku") is True, "再切一次重新开启")
    ev(win, "library.close(); settings.show()")
    settle(400)
    check(not [w for w in WARNINGS if "SettingsPage" in w or "LibraryPanel" in w], "面板和设置页没有 QML 警告",
          "; ".join(WARNINGS[:3]))
    finish()

elif PHASE == "read":
    p = ev(win, f"JSON.stringify(Store.progressOf('{DRAMA}'))")
    check('"ep":3' in (p or "") and "测试剧" in (p or ""), "重启后观看进度还在", p)
    check(ev(win, "Store.searches.length") == 10 and ev(win, "Store.searches[0]") == "回车词", "重启后搜索记录还在",
          ev(win, "Store.searches.join(',')"))
    h = ev(win, "Store.history().map(h => h.id).join(',')")
    check(h == f"{DRAMA},{EPS}", "重启后观看历史还在（最近看的在前，信息流剧不在里面）", h)
    check(ev(win, f"Store.progressOf('{FEED}') !== null") is True, "信息流剧的进度重启后也在")
    check(ev(win, f"String((MockData.drama('{FEED}') || {{}}).id)") != FEED, "信息流剧不并回剧单（只并历史里的）")
    check(ev(win, f"MockData.drama('{DRAMA}').title") == "测试剧", "历史里的剧并回剧单（不在推荐流里也能打开）")
    feed = [{"id": "7700000000000000099", "title": "推荐剧", "episode_count": 10, "cover_url": ""}]
    backend._apply_items("推荐", feed)
    ids = [d["id"] for d in backend._dramas]
    check(ids[0] == "7700000000000000099" and DRAMA in ids, "换频道重建剧单后历史剧仍在", ids)

    # 收藏夹重启后
    check(ev(win, "Store.favorites.map(f => f.id).join(',')") == f"{LONG},{FAV}", "重启后收藏夹还在",
          ev(win, "Store.favorites.map(f => f.id).join(',')"))
    check(ev(win, f"MockData.drama('{LONG}').title") == "长集剧", "收藏的剧并回剧单（没进历史也能打开）")
    # 重启后没有剧集信息：FAV 靠时长快照判断已看完 → 下一集开头；LONG 时长未知 → 接着 100 秒播（以前按 90 秒兜底会跳集）
    check(ev(win, f"JSON.stringify(player.startOf('{FAV}'))") == '{"ep":6,"pos":0}', "已看完的集：续播下一集开头",
          ev(win, f"JSON.stringify(player.startOf('{FAV}'))"))
    check(ev(win, f"JSON.stringify(player.startOf('{LONG}'))") == '{"ep":2,"pos":100}', "时长未知：接着上次的位置播",
          ev(win, f"JSON.stringify(player.startOf('{LONG}'))"))
    # 从收藏夹点开：续播 + 进全剧界面
    ev(win, "library.show('favorites')")
    settle(300)
    check(ev(field, "lib.items.length") == 2, "收藏夹面板列出 2 部", ev(field, "lib.items.length"))
    ev(field, f"lib.choose('{LONG}')")
    settle(300)
    check(ev(win, "String(player.dramaId)") == LONG and ev(win, "player.currentEp") == 2,
          "点开收藏：打开的是记录的那一集", f"{ev(win, 'String(player.dramaId)')} 第 {ev(win, 'player.currentEp')}")
    check(ev(win, "player.dramaMode") is True, "点开收藏：直接进全剧界面")
    check(ev(win, "library.open") is False, "点开后面板关闭")
    # 从观看历史点开同理
    ev(win, "library.show('history')")
    settle(300)
    ev(field, f"lib.choose('{DRAMA}')")
    settle(300)
    check(ev(win, "String(player.dramaId)") == DRAMA and ev(win, "player.currentEp") == 3 and ev(win, "player.dramaMode") is True,
          "点开历史：续播记录的那一集并进全剧界面")
    # 清空观看历史：收藏的剧进度保留（仍能续播），只是移出历史
    ev(win, "Store.clearHistory()")
    check(ev(win, "Store.history().length") == 0, "观看历史已清空")
    check(ev(win, f"Store.progressOf('{FAV}') !== null && Store.progressOf('{EPS}') === null") is True,
          "清空历史后收藏的剧还有进度，其余的清掉")
    check(ev(win, f"Store.toggleFavorite('{LONG}')") is False and ev(win, "Store.favorites.length") == 1, "取消收藏")
    finish()

elif PHASE == "reset":
    check(ev(win, "Store.searches.length") == 10, "重置前数据还在")
    cache = os.path.join(os.environ["LOCALAPPDATA"], "IHaveApple", "cache", "covers")
    upd = os.path.join(os.environ["TEMP"], "IHaveApple-update")
    for d in (cache, upd):
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "x.bin"), "wb").close()
    QTimer.singleShot(300, lambda: ev(win, "Backend.resetAll()"))
    QTimer.singleShot(8000, app.quit)       # 兜底：信号没把界面关掉
    app.exec()
    check(backend.reset_requested, "点「完全重置」后界面退出")
    # 和 main.py 一样：先销毁引擎再清
    player.shutdown()
    backend.shutdown()
    shiboken6.delete(engine)
    backend.wipe_all()
    QSettings().sync()
    keys = QSettings().allKeys()
    check(keys == [], "注册表里的设置 / 记录已清空（没被 QML 写回）", keys)
    check(not os.path.exists(os.path.dirname(cache)), "缓存目录已删除")
    check(not os.path.exists(upd), "更新包目录已删除")

sys.exit(1 if FAILED else 0)
