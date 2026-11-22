# IHaveApple

沉浸式竖屏短剧播放器（Windows）。整个应用只有一个播放界面：窗口锁定 9:16，画面铺满窗口，标题栏和控件叠加在画面上、鼠标静止后自动隐藏。

- 上下拖动画面，像刷短视频一样跟手切换；滚轮、↑↓ 键同样可以切换
- 自动预载接下来 5 个节目，切换基本无缝
- 选集面板、搜索、观看历史、设置（快捷键、自动连播、最小化暂停等）
- 播放内核是 libmpv，界面是 Qt 6 QML

设计文档见 [docs/windows-ui-design.md](docs/windows-ui-design.md)。

## 下载运行

从 [Releases](../../releases) 下载 `IHaveApple-<版本>-win64.zip`，解压后运行 `IHaveApple.exe`。

压缩包里带有：

| 目录 | 内容 |
|---|---|
| `IHaveApple.exe`、`_internal/` | 播放器（含 libmpv） |
| `hgd/` | 片源服务 `ohgd.exe` 和它的 `config.json`，播放器启动时自动拉起 |
| `ffmpeg/` | `ohgd` 转封装、播放器转封面用的 ffmpeg |

**片源服务还依赖一个签名服务**：`ohgd` 的播放接口需要真实签名，默认连 `http://127.0.0.1:19830`（见 `hgd/config.json` 的 `signer_url`）。
签名服务是 [openhongguo](https://github.com/beilunyang/openhongguo) 里的 `signer/`（Java 21），压缩包里不带，需要自行构建运行。
没有签名服务时可以打开界面、浏览剧单，但拿不到播放地址。

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

推送 `v*` 标签会触发 GitHub Actions（[.github/workflows/release.yml](.github/workflows/release.yml)）：下载 libmpv 和 ffmpeg，编译 `ohgd`，用 PyInstaller 打包播放器，把 zip 发布到对应的 Release。

本地打包：

```powershell
pip install pyinstaller
pwsh scripts/build-windows.ps1 -Version dev -Mpv prototype/lib/libmpv-2.dll -Ffmpeg (Get-Command ffmpeg).Source
```

## 许可

- `sdk/openhongguo/`：Apache License 2.0
- 字体：HarmonyOS Sans（`prototype/fonts/HarmonyOS_Sans_LICENSE.txt`）、得意黑 Smiley Sans（SIL OFL 1.1）
- 打包进 Release 的 libmpv、ffmpeg 遵循各自的许可（GPL）
