# IHaveApple

沉浸式竖屏短剧播放器（Windows）。整个应用只有一个播放界面：窗口锁定 9:16，画面铺满窗口，标题栏和控件叠加在画面上、鼠标静止后自动隐藏。

- 上下拖动画面，像刷短视频一样跟手切换；滚轮、↑↓ 键同样可以切换
- 自动预载接下来 5 个节目，切换基本无缝
- 选集面板、搜索、观看历史、设置（快捷键、自动连播、最小化暂停等）
- 播放内核是 libmpv，界面是 Qt 6 QML

设计文档见 [docs/windows-ui-design.md](docs/windows-ui-design.md)。

## 下载安装

从 [Releases](../../releases) 下载 `IHaveApple-Setup-<版本>-win64.exe`，双击运行安装向导，安装目录可以自己选（默认 `%LOCALAPPDATA%\Programs\IHaveApple`）。
安装完成后从开始菜单或桌面快捷方式启动；卸载在「设置 → 应用 → 已安装的应用」里操作。

安装目录里带有：

| 目录 | 内容 |
|---|---|
| `IHaveApple.exe`、`_internal/` | 播放器（含 libmpv） |
| `hgd/` | 片源服务 `ohgd.exe` 和它的 `config.json`，播放器启动时自动拉起；签名已内置 |
| `ffmpeg/` | `ohgd` 转封装、播放器转封面用的 ffmpeg |

签名已经编译在 `ohgd` 里，安装后直接运行即可播放，不需要安装 Java，也不需要单独启动签名服务。
如果以后内置签名失效，可以在 `hgd/config.json` 把 `signer_url` 指向 [openhongguo](https://github.com/beilunyang/openhongguo) 的 `signer/`（Java 21）改用外部签名；留空则使用内置实现。

## 开发

```powershell
pip install -r prototype/requirements.txt
python prototype/main.py
```

- 需要 Python 3.10+、ffmpeg（在 PATH 里），以及 `prototype/lib/libmpv-2.dll`（从 [mpv-winbuild-cmake](https://github.com/shinchiro/mpv-winbuild-cmake/releases) 的 `mpv-dev-x86_64-*.7z` 里取）。
- 播放器默认用 `../hongguo/hgd/ohgd.exe` 作为片源服务，可以用环境变量 `IHAVEAPPLE_SDK` 指向别的目录（目录里要有 `ohgd.exe` 和 `config.json`）。
- `ohgd` 的源码在 `sdk/hgd/`，依赖 `sdk/openhongguo/`（openhongguo 的部分源码，改动见 [MODIFIED.md](sdk/openhongguo/MODIFIED.md)）。编译：`cd sdk/hgd; go build .`
- 更多原型说明见 [prototype/README.md](prototype/README.md)。

## 打包与发布

推送 `v*` 标签会触发 GitHub Actions（[.github/workflows/release.yml](.github/workflows/release.yml)）：下载 libmpv 和 ffmpeg，编译 `ohgd`，用 PyInstaller 打包播放器，再用 Inno Setup 生成安装包，发布到对应的 Release。
打包脚本会校验 `hgd/config.json` 的 `signer_url` 为空，确保发行包使用 `ohgd` 内置签名、不依赖外部服务。

本地打包：

```powershell
pip install pyinstaller
scoop install extras/inno-setup   # 或装 Inno Setup 6.3+，也可以稍后用 -Iscc 指定 ISCC.exe
pwsh scripts/build-windows.ps1 -Version dev -Mpv prototype/lib/libmpv-2.dll -Ffmpeg (Get-Command ffmpeg).Source
# 注意 ffmpeg 要传真实的 ffmpeg.exe（不是 scoop 的 shim），生成的安装包在 dist/IHaveApple-Setup-dev-win64.exe
```

## 许可

- `sdk/openhongguo/`：Apache License 2.0
- 字体：HarmonyOS Sans（`prototype/fonts/HarmonyOS_Sans_LICENSE.txt`）、得意黑 Smiley Sans（SIL OFL 1.1）
- 打包进 Release 的 libmpv、ffmpeg 遵循各自的许可（GPL）
