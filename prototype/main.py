"""IHaveApple Windows UI 原型启动器。

只负责：注册字体、读取系统"动画效果"设置、加载 QML。
界面全部在 qml/ 目录中，后续迁移到 C++（Qt 6 + libmpv）时 QML 可直接复用。

用法：
    python main.py                                   # 按竖屏比例自动确定窗口大小
    python main.py --drama 3 --size 1440x900 --shot out.png   # 截图后退出
可用 --page（演示状态）：player / episodes / search / history / settings / end / error / offline / immersive
"""

import argparse
import ctypes
import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, QUrl
from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonType, qmlRegisterType
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from hgservice import HgService
from mpv_player import MpvPlayer
from video_item import VideoItem, bind_player
from native_window import install_aspect_resize

ROOT = Path(__file__).resolve().parent
FONTS = [
    "HarmonyOS_Sans_SC_Regular.ttf",
    "HarmonyOS_Sans_SC_Medium.ttf",
    "HarmonyOS_Sans_SC_Bold.ttf",
    "SmileySans-Oblique.ttf",
]


def system_reduced_motion() -> bool:
    """Windows「设置 → 辅助功能 → 动画效果」关闭时返回 True。"""
    if sys.platform != "win32":
        return False
    SPI_GETCLIENTAREAANIMATION = 0x1042
    enabled = ctypes.c_bool(True)
    ok = ctypes.windll.user32.SystemParametersInfoW(
        SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0
    )
    return bool(ok) and not enabled.value


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--page", default="player")
    # 0 = 不指定，首屏用后端推荐（每次启动换一部）；1 起的序号或完整剧 id 可指定
    p.add_argument("--drama", default="0", help="剧序号（1 起）/ 剧 id；留空则首屏推荐")
    p.add_argument("--size", default="", help="如 1440x900，留空则自动")
    p.add_argument("--shot", default="")
    p.add_argument("--reduced-motion", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    width, height = (int(v) for v in args.size.lower().split("x")) if args.size else (0, 0)

    QQuickStyle.setStyle("Basic")
    if args.shot:
        # grabWindow() 会在持有 GIL 时等渲染线程，而 VideoItem 在渲染线程里要 GIL → 死锁（见 video_item.py）
        os.environ["QSG_RENDER_LOOP"] = "basic"
    # 用 QApplication 而不是 QGuiApplication：托盘图标的右键菜单（Qt.labs.platform）在 Windows 上依赖 Qt Widgets
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(ROOT / "assets" / "icon.svg")))
    app.setOrganizationName("IHaveApple")
    # 用户设置由 QML 的 QtCore.Settings 持久保存。截图模式使用独立且每次清空的存储，结果可复现
    app.setApplicationName("IHaveApple-shot" if args.shot else "IHaveApple")
    if args.shot:
        QSettings().clear()

    for name in FONTS:
        if QFontDatabase.addApplicationFont(str(ROOT / "fonts" / name)) < 0:
            print(f"[warn] 字体加载失败：{name}，将使用回退字体", file=sys.stderr)

    # 播放内核（libmpv → QVideoSink）与数据后端（本地 SDK）
    # 注册为 QML 单例，QML 各文件（含 pragma Singleton）都能 import 使用
    player = MpvPlayer()
    backend = HgService()
    app._player = player      # 持有引用，避免被回收
    app._backend = backend
    bind_player(player)
    qmlRegisterType(VideoItem, "IHaveApple", 1, 0, "VideoItem")
    qmlRegisterSingletonType(MpvPlayer, "IHaveApple", 1, 0, "Player", lambda _e: player)
    qmlRegisterSingletonType(HgService, "IHaveApple", 1, 0, "Backend", lambda _e: backend)

    engine = QQmlApplicationEngine()

    def _qml_warn(ws):
        for w in ws:
            print("[qml]", w.toString(), file=sys.stderr, flush=True)
    engine.warnings.connect(_qml_warn)

    ctx = engine.rootContext()
    ctx.setContextProperty("launchPage", args.page)
    # 短序号转成 int（QML 里要比较 > 0），19 位剧 id 保留字符串，避免精度丢失
    launch_drama = int(args.drama) if args.drama.isdigit() and len(args.drama) < 10 else args.drama
    ctx.setContextProperty("launchDrama", launch_drama)
    ctx.setContextProperty("launchWidth", width)
    ctx.setContextProperty("launchHeight", height)
    ctx.setContextProperty("launchShot", bool(args.shot))
    ctx.setContextProperty("systemReducedMotion", args.reduced_motion or system_reduced_motion())
    ctx.setContextProperty("nativeAspectResize", sys.platform == "win32")

    engine.load(QUrl.fromLocalFile(str(ROOT / "qml" / "Main.qml")))
    if not engine.rootObjects():
        return 1

    # 后台拉剧单，不阻塞 UI 首帧
    backend.load_async()
    # 等比缩放（Windows）：窗口有 winId 之后才能子类化窗口过程，所以放在 load 之后。
    # 锁定比例由 Main.qml 的 windowAspectRequested 信号驱动（「窗口适配视频比例」会改它）。
    window = engine.rootObjects()[0]
    aspect_hook = install_aspect_resize(window, 9 / 16, 640)  # noqa: F841
    if aspect_hook is not None:
        window.windowAspectRequested.connect(aspect_hook.set_aspect)
        aspect_hook.set_aspect(window.property("windowAspect"))

    if args.shot:
        window = engine.rootObjects()[0]

        def save_shot():
            ok = window.grabWindow().save(str(Path(args.shot).resolve()))
            print(f"截图{'已保存' if ok else '保存失败'}：{args.shot}")
            app.quit()

        QTimer.singleShot(22000, save_shot)

    rc = app.exec()
    player.shutdown()
    backend.shutdown()
    return rc


if __name__ == "__main__":
    sys.exit(main())
