# 更新日志

本项目的版本变更都记录在这里。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

## [v0.1.5] - 2026-11-23

### 新增

- 检查更新：启动后自动检查 GitHub Release，运行期间每 6 小时再查一次；有新版本时提示是否下载，确认后下载安装包并静默安装到当前目录，装完自动重新打开播放器。点过「稍后」的版本在本次运行内不再重复提示
- 设置页「关于」显示当前版本，可手动「检查更新」，也可关闭「启动时自动检查更新」
- 更新渠道可选「GitHub 官方」（默认）或「ghfast.top 镜像」，GitHub 连不上或下载慢时使用

### 变更

- 打包时把版本号写入程序（`version.txt`），播放器据此判断是否有新版本

### 修复

- 底部简介区紧贴进度条，渐变和控件栏连成一片，不再中间空出一截
- 打开设置、搜索、观看历史时，顶部标题栏和频道 tab 区域铺上实色底，不再透出后面的画面

## [v0.1.4] - 2026-11-23

### 新增

- 设置页可自选缓存目录，实时显示缓存占用，支持一键清理

### 变更

- 默认缓存迁到 `%LOCALAPPDATA%\IHaveApple\cache`，不再写入安装目录；卸载时一并清理

## [v0.1.3] - 2026-11-23

### 新增

- 推荐流可持续加载新节目；再点当前频道直接换一批
- 窗口按片源比例自动调整，窗口落在已断开的显示器上时自动移回主屏
- 新增 `--screen` 参数，指定在哪块显示器上启动

### 变更

- Windows 版改为 Inno Setup 安装包发布，安装目录可选，卸载后不留运行缓存
- 简介随控件一起自动隐藏，不再常驻
- 隐藏「AI剧」tab（上游没有该频道）

### 修复

- 关闭播放器（包括被强制结束）后不再残留 `ohgd` 进程

## [v0.1.2] - 2026-11-23

### 新增

- `ohgd` 支持 `--pad` 平板身份

### 修复

- 跟随上游播放接口变更（`/novel/player/multi_video_model/v1/`），修复起播失败
- 修复错误遮罩与「全剧终」页上鼠标光标不可见

## [v0.1.1] - 2026-11-22

### 修复

- 修复发行包缺少签名服务：改用 `ohgd` 内置签名，解压后直接可用，不再需要 Java 或单独启动签名服务

## [v0.1.0] - 2026-11-22

### 新增

- 首个版本：沉浸式竖屏短剧播放器（Windows x64）
- 窗口即视频：9:16 竖屏铺满，控件叠加在画面上，鼠标静止后自动隐藏
- 上下拖动画面跟手切换，滚轮、↑↓ 同样可以切换；进入选集后改为翻上下集
- 预载接下来 5 个节目，切换基本无缝
- 进度条精准跳转，未缓存的集也能拖到任意位置
- 选集面板、搜索、观看历史、设置（快捷键、自动连播、最小化暂停、清晰度、倍速等）

[未发布]: https://github.com/LemonYangZW/IHaveApple/compare/v0.1.5...HEAD
[v0.1.5]: https://github.com/LemonYangZW/IHaveApple/compare/v0.1.4...v0.1.5
[v0.1.4]: https://github.com/LemonYangZW/IHaveApple/compare/v0.1.3...v0.1.4
[v0.1.3]: https://github.com/LemonYangZW/IHaveApple/compare/v0.1.2...v0.1.3
[v0.1.2]: https://github.com/LemonYangZW/IHaveApple/compare/v0.1.1...v0.1.2
[v0.1.1]: https://github.com/LemonYangZW/IHaveApple/compare/v0.1.0...v0.1.1
[v0.1.0]: https://github.com/LemonYangZW/IHaveApple/releases/tag/v0.1.0
