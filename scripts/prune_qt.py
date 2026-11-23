"""修剪 PyInstaller 打出来的 PySide6：删掉播放器用不到的 Qt 模块，安装包更小、打包更快。

PyInstaller 的 QtQml 钩子会把 PySide6 自带的全部 QML 模块（3D、图表、地图、多媒体……）连同插件和 DLL 一起收进来，
光这些就有上百 MB。这里分两步删：

1. 按清单删掉用不到的 QML 模块、Qt 插件目录和翻译文件（清单见下方常量，用到的模块见 qml/*.qml 的 import）；
2. 从剩下的 .pyd、Qt 插件、QML 插件出发，沿 PE 导入表找出真正被引用的 Qt6*.dll，其余 Qt6*.dll 删除。
   只删 Qt6*.dll：OpenSSL、d3dcompiler 这类运行时按名字动态加载的库导入表里看不到，一律不碰。

用法：python scripts/prune_qt.py dist/IHaveApple
"""
import os
import shutil
import sys

import pefile

# QML 模块：只保留这些（qml/ 下的顶层目录 / 子目录，相对 PySide6/qml）
QML_KEEP_TOP = {"QtCore", "QtQml", "QtQuick", "Qt"}
QML_DROP = [
    # QtQuick 下用不到的子模块（保留 Controls / Templates / Effects / Shapes / Layouts / Window）
    "QtQuick/Dialogs", "QtQuick/LocalStorage", "QtQuick/NativeStyle", "QtQuick/Particles",
    "QtQuick/Scene2D", "QtQuick/Scene3D", "QtQuick/Timeline", "QtQuick/VectorImage",
    "QtQuick/VirtualKeyboard", "QtQuick/tooling", "QtQuick/Pdf",
    # 控件只用 Basic 风格（main.py 里 QQuickStyle.setStyle("Basic")）
    "QtQuick/Controls/FluentWinUI3", "QtQuick/Controls/Fusion", "QtQuick/Controls/Imagine",
    "QtQuick/Controls/Material", "QtQuick/Controls/Native", "QtQuick/Controls/Universal",
    "QtQuick/Controls/Windows", "QtQuick/Controls/designer",
]
QML_KEEP_LABS = {"platform"}          # Qt.labs.*：只用到托盘（Qt.labs.platform）
# Qt 插件目录：只保留这些
PLUGINS_KEEP = {"platforms", "imageformats", "iconengines", "styles", "tls"}
PLUGINS_DROP_FILES = ["imageformats/qpdf.dll"]    # 会拖进 Qt6Pdf
# 不是导入依赖、而是按需加载的大文件：软件 OpenGL 用不到（Qt Quick 在 Windows 走 D3D11，显卡不行时退到 WARP；
# 视频由 mpv 软件渲染）
DROP_FILES = ["opengl32sw.dll"]


def _rm(path, removed):
    if os.path.isdir(path):
        removed.append(path)
        shutil.rmtree(path)
    elif os.path.isfile(path):
        removed.append(path)
        os.remove(path)


def _imports(path):
    try:
        pe = pefile.PE(path, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                               pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
        names = [e.dll.decode("ascii", "replace") for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])]
        names += [e.dll.decode("ascii", "replace") for e in getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])]
        pe.close()
        return [n.lower() for n in names]
    except pefile.PEFormatError:
        return []


def _size(root):
    return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(root) for f in fs)


def prune(app_dir):
    internal = os.path.join(app_dir, "_internal")
    pyside = os.path.join(internal, "PySide6")
    qml = os.path.join(pyside, "qml")
    plugins = os.path.join(pyside, "plugins")
    if not os.path.isdir(pyside):
        raise SystemExit(f"找不到 {pyside}")
    before = _size(app_dir)
    removed = []

    # 1) 清单
    for name in os.listdir(qml):
        if os.path.isdir(os.path.join(qml, name)) and name not in QML_KEEP_TOP:
            _rm(os.path.join(qml, name), removed)
    for rel in QML_DROP:
        _rm(os.path.join(qml, *rel.split("/")), removed)
    labs = os.path.join(qml, "Qt", "labs")
    if os.path.isdir(labs):
        for name in os.listdir(labs):
            if name not in QML_KEEP_LABS:
                _rm(os.path.join(labs, name), removed)
    for name in os.listdir(plugins):
        if name not in PLUGINS_KEEP:
            _rm(os.path.join(plugins, name), removed)
    for rel in PLUGINS_DROP_FILES:
        _rm(os.path.join(plugins, *rel.split("/")), removed)
    for name in DROP_FILES:
        _rm(os.path.join(pyside, name), removed)
    _rm(os.path.join(pyside, "translations"), removed)   # 没装 QTranslator，Qt 不会自己加载

    # 2) 导入闭包：根 = 主程序、所有 .pyd、剩下的 Qt 插件和 QML 插件
    by_name = {}
    for d, _, fs in os.walk(app_dir):
        for f in fs:
            if f.lower().endswith((".dll", ".pyd", ".exe")):
                by_name.setdefault(f.lower(), os.path.join(d, f))
    roots = [p for n, p in by_name.items()
             if n.endswith((".pyd", ".exe")) or p.startswith((qml + os.sep, plugins + os.sep))]
    seen, stack = set(), list(roots)
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        stack += [by_name[n] for n in _imports(p) if n in by_name]
    for f in sorted(os.listdir(pyside)):
        p = os.path.join(pyside, f)
        if f.lower().startswith("qt6") and f.lower().endswith(".dll") and p not in seen:
            _rm(p, removed)

    after = _size(app_dir)
    print(f"修剪 Qt：删除 {len(removed)} 项，{before / 2**20:.0f} MB → {after / 2**20:.0f} MB")
    for p in removed:
        print("  -", os.path.relpath(p, app_dir))


if __name__ == "__main__":
    prune(sys.argv[1] if len(sys.argv) > 1 else os.path.join("dist", "IHaveApple"))
