"""验收：首屏推荐在真实 UI 里生效（不是同一部、只起播一次、进观看历史）。

连续两次启动完整的 Main.qml，比对首屏播放的剧。
用法：python -I tools/verify_feed_ui.py
"""
import json
import os
import sys

os.environ["QSG_RENDER_LOOP"] = "basic"

from PySide6.QtCore import QSettings, QTimer, QUrl            # noqa: E402
from PySide6.QtGui import QFontDatabase                       # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlRegisterSingletonType, qmlRegisterType  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle              # noqa: E402
from PySide6.QtTest import QTest                              # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

PROTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROTO)
OUT = os.path.join(PROTO, "shots", "feed_ui")
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


def launch(run_index):
    """启动一次完整界面，返回 (剧id, 标题, prepare 次数)。"""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setOrganizationName("IHaveApple")
    app.setApplicationName("IHaveApple-feed")       # 固定存储名，才能验证「换一部」
    for f in os.listdir(os.path.join(PROTO, "fonts")):
        if f.endswith(".ttf"):
            QFontDatabase.addApplicationFont(os.path.join(PROTO, "fonts", f))

    player, backend = MpvPlayer(), HgService()
    curve_warning = []
    bind_player(player)
    qmlRegisterType(VideoItem, "IHaveApple", 1, 0, "VideoItem")
    qmlRegisterSingletonType(MpvPlayer, "IHaveApple", 1, 0, "Player", lambda _e: player)
    qmlRegisterSingletonType(HgService, "IHaveApple", 1, 0, "Backend", lambda _e: backend)

    engine = QQmlApplicationEngine()
    engine.warnings.connect(lambda ws: [curve_warning.append(w.toString()) for w in ws])
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
        return v[0] if isinstance(v, tuple) else v

    state = {}

    def wait_playing(n=[0]):
        n[0] += 1
        drama = ev(win, "player.drama")
        if (drama and ev(win, "player.stage.phase") == "playing") or n[0] > 90:
            state["drama"] = drama
            state["dramaId"] = str(ev(win, "player.dramaId"))
            # QJSValue 不能直接迭代，走 JSON 转一手
            state["history"] = json.loads(ev(win, "JSON.stringify(Store.history())") or "[]")
            state["recommend"] = str(ev(win, "Backend.recommendId"))
            state["warn"] = list(curve_warning)
            # 只拉了推荐那部的分集 → 说明没有先偷偷播第一部
            state["episode_dramas"] = list(backend._episodes.keys())
            QTest.qWait(1200)
            win.grabWindow().save(os.path.join(OUT, f"{run_index}.png"))
            backend.shutdown()
            player.shutdown()
            engine.deleteLater()
            QTimer.singleShot(400, lambda: app.quit())
        else:
            QTimer.singleShot(400, wait_playing)

    QTimer.singleShot(20000, wait_playing)
    QTimer.singleShot(60000, app.quit)
    app.exec()
    QTest.qWait(600)
    return state


log("=== 启动真实界面 ===")
QSettings().clear()          # 干净起点
r1 = launch(1)
title1 = r1.get("drama", {}).get("title", "") if r1.get("drama") else ""
log(f"  首屏: {title1}  dramaId={r1.get('dramaId')}  推荐={r1.get('recommend')}")
check(bool(title1), "首屏有画面")
check(r1.get("dramaId") == r1.get("recommend"), "dramaId 已同步为推荐剧",
      f"{r1.get('dramaId')} vs {r1.get('recommend')}")
check(len(r1.get("episode_dramas", [])) == 1, "只拉了推荐那一部的分集（没先播第一部）",
      str(r1.get("episode_dramas")))
hist_ids = [str(h["id"]) for h in (r1.get("history") or [])]
check(r1.get("recommend") in hist_ids, "推荐剧进入观看历史", str(hist_ids))
qml_err = [w for w in r1.get("warn", []) if "ReferenceError" in w or "is not defined" in w
           or "TypeError" in w]
check(not qml_err, "无 QML 报错", str(qml_err[:2]))

QSettings().clear()
log("\n注：多次启动是否会换剧由 tools/verify_recommend.py 覆盖（同进程重复注册 QML 单例会冲突，")
log("    所以这里只验证一次完整界面）。")
log("\n结论：" + ("全部通过" if not FAILED else f"失败项 {FAILED}"))
sys.exit(0 if not FAILED else 1)
