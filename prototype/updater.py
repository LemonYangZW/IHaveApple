"""updater — 检查 GitHub Release 上的新版本，下载安装包并静默安装

QML 用法（注册为单例 `Updater`）：
    Updater.version / latestVersion / notes / state / progress
    Updater.check(manual, channel)  // manual=true 时「已是最新」「检查失败」也会提示
    Updater.download(channel)       // 下载最新安装包，完成后自动运行安装并退出播放器
    Updater.cancel()                // 取消下载
    signal quitRequested()          // 安装包已启动，播放器该退出了（释放文件给安装程序覆盖）

channel 是更新渠道（见 MIRRORS）：official 直连 GitHub，其余在 GitHub 地址前加镜像前缀。
镜像不代理 api.github.com，所以两个渠道都不走 API，而是：
  · releases/latest 会 302 到 releases/tag/<标签>，从跳转地址取最新版本号
  · 安装包名由打包脚本固定为 IHaveApple-Setup-<标签>-win64.exe，HEAD 一下确认已上传、拿到大小
  · 更新说明读该标签下的 .github/release-notes.md（就是 Release 正文的来源）
顺带也避开了 API 未登录每小时 60 次的限额。

版本号由打包脚本写入 version.txt（见 scripts/build-windows.ps1）；开发时没有该文件，
版本为 "dev"，不自动检查。测试可用环境变量 IHAVEAPPLE_VERSION 假装成某个版本。
"""

import os
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import Property, QObject, Signal, Slot

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.path.dirname(sys.executable) if FROZEN else HERE
REPO = "LemonYangZW/IHaveApple"
GITHUB = f"https://github.com/{REPO}"
RAW = f"https://raw.githubusercontent.com/{REPO}"
# 更新渠道 -> 加在 GitHub 地址前面的前缀（设置页的选项与这里的键一致）
MIRRORS = {
    "official": "",
    "ghfast": "https://ghfast.top/",
}
UA = {"User-Agent": "IHaveApple-Updater"}
CHUNK = 256 * 1024


def _via(channel, url):
    return MIRRORS.get(channel, "") + url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None             # 不跟跳转：302 会以 HTTPError 抛出，从 Location 里取标签


_no_redirect = urllib.request.build_opener(_NoRedirect)


def _latest_tag(channel):
    req = urllib.request.Request(_via(channel, GITHUB + "/releases/latest"), headers=UA)
    try:
        _no_redirect.open(req, timeout=15).close()
        location = ""
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308):
            raise
        location = e.headers.get("Location") or ""
    # 官方给完整地址，镜像给 /https://github.com/... 这样的相对地址，都以 /releases/tag/<标签> 结尾
    m = re.search(r"/releases/tag/([^/?#]+)$", location)
    if not m:
        raise ValueError(f"识别不出最新版本：{location or '没有跳转'}")
    return urllib.parse.unquote(m.group(1))


def _asset_size(channel, url):
    """安装包大小；还没上传（发布流程先建 Release 再传安装包，中间有几分钟空档）返回 None。"""
    req = urllib.request.Request(_via(channel, url), method="HEAD", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return int(r.headers.get("Content-Length") or 0)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _release_notes(channel, tag):
    """该版本的发行说明；拿不到不影响更新，只是弹窗里不显示更新内容。"""
    req = urllib.request.Request(_via(channel, f"{RAW}/{tag}/.github/release-notes.md"), headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"[update] 读取更新说明失败：{e}", flush=True)
        return ""


def _read_version():
    env = os.environ.get("IHAVEAPPLE_VERSION")
    if env:
        return env.strip()
    try:
        with open(os.path.join(HERE, "version.txt"), encoding="utf-8-sig") as f:
            return f.read().strip() or "dev"
    except OSError:
        return "dev"


def parse_version(text):
    """"v0.1.10" → (0, 1, 10)；不是正式版本号（dev、dev-abc1234）返回 None。"""
    m = re.fullmatch(r"[vV]?(\d+(?:\.\d+){0,3})", (text or "").strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def _notes_since(body, current):
    """从发行说明「- v0.1.4：…」这样的行里，挑出比当前版本新的几条。"""
    lines = []
    for line in (body or "").splitlines():
        m = re.match(r"^\s*[-*]\s*(v[\d.]+)\s*[：:]\s*(.+)$", line.strip())
        if m and (parse_version(m.group(1)) or ()) > current:
            lines.append(f"{m.group(1)}：{m.group(2).strip()}")
    return "\n".join(lines)


class Updater(QObject):
    # state：idle | checking | latest | available | downloading | installing | error
    changed = Signal()
    updateAvailable = Signal(bool)  # 检查到新版本（参数：是否手动检查），界面据此弹出更新提示
    toast = Signal(str)
    quitRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._version = _read_version()
        self._state = "idle"
        self._latest = ""
        self._notes = ""
        self._asset = None        # {name, url, size}
        self._progress = 0.0
        self._cancel = threading.Event()

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, "_" + k, v)
        self.changed.emit()

    # ---------- 属性 ----------
    @Property(str, constant=True)
    def version(self):
        return self._version

    @Property(bool, constant=True)
    def canCheck(self):
        """开发版没有正式版本号，比较不出新旧。"""
        return parse_version(self._version) is not None

    @Property(str, notify=changed)
    def state(self):
        return self._state

    @Property(str, notify=changed)
    def latestVersion(self):
        return self._latest

    @Property(str, notify=changed)
    def notes(self):
        return self._notes

    @Property(float, notify=changed)
    def progress(self):
        return self._progress

    # ---------- 检查 ----------
    @Slot(bool, str)
    def check(self, manual, channel):
        if self._state in ("checking", "downloading", "installing"):
            return
        if not self.canCheck:
            if manual:
                self.toast.emit("开发版不检查更新")
            return
        self._set(state="checking")
        threading.Thread(target=self._check, args=(manual, channel), daemon=True).start()

    def _check(self, manual, channel):
        try:
            tag = _latest_tag(channel)
            latest, current = parse_version(tag), parse_version(self._version)
            name = f"IHaveApple-Setup-{tag}-win64.exe"
            url = f"{GITHUB}/releases/download/{tag}/{name}"
            size = _asset_size(channel, url) if latest and latest > current else None
            if size is None:
                self._set(state="latest", latest=tag)
                if manual:
                    self.toast.emit(f"已是最新版本 {self._version}")
                return
            self._set(state="available", latest=tag, asset={"name": name, "url": url, "size": size},
                      notes=_notes_since(_release_notes(channel, tag), current))
            print(f"[update] 发现新版本 {tag}（当前 {self._version}，渠道 {channel}）", flush=True)
            self.updateAvailable.emit(manual)
        except Exception as e:
            print(f"[update] 检查更新失败（渠道 {channel}）：{e}", flush=True)
            self._set(state="error")
            if manual:
                self.toast.emit("检查更新失败，可以在设置里换个更新渠道再试")

    # ---------- 下载与安装 ----------
    @Slot(str)
    def download(self, channel):
        if self._state != "available" or not self._asset:
            return
        self._cancel.clear()
        self._set(state="downloading", progress=0.0)
        threading.Thread(target=self._download, args=(self._asset, channel), daemon=True).start()

    @Slot()
    def cancel(self):
        self._cancel.set()

    def _download(self, asset, channel):
        folder = os.path.join(tempfile.gettempdir(), "IHaveApple-update")
        target = os.path.join(folder, asset["name"])
        part = target + ".part"
        try:
            os.makedirs(folder, exist_ok=True)
            # 之前下完但没装上的同名安装包，大小对得上就直接用
            if not (asset["size"] and os.path.exists(target) and os.path.getsize(target) == asset["size"]):
                req = urllib.request.Request(_via(channel, asset["url"]), headers=UA)
                with urllib.request.urlopen(req, timeout=30) as r, open(part, "wb") as f:
                    total = asset["size"] or int(r.headers.get("Content-Length") or 0)
                    done = 0
                    while chunk := r.read(CHUNK):
                        if self._cancel.is_set():
                            raise InterruptedError
                        f.write(chunk)
                        done += len(chunk)
                        if total:
                            self._progress = min(done / total, 1.0)
                            self.changed.emit()
                if total and done != total:
                    raise IOError(f"下载不完整（{done}/{total} 字节）")
                os.replace(part, target)
        except InterruptedError:
            self._discard(part)
            self._set(state="available", progress=0.0)
            self.toast.emit("已取消下载")
            return
        except Exception as e:
            print(f"[update] 下载失败：{e}", flush=True)
            self._discard(part)
            self._set(state="available", progress=0.0)
            self.toast.emit("下载更新失败，可以稍后重试或在设置里换个更新渠道")
            return
        self._install(target)

    @staticmethod
    def _discard(path):
        try:
            os.remove(path)
        except OSError:
            pass

    def _install(self, setup):
        if not FROZEN:
            self._set(state="available")
            self.toast.emit(f"开发环境不运行安装包，已下载到 {setup}")
            return
        # /SILENT 只显示进度窗口；/DIR 装回当前目录；/relaunch=1 让安装包装完后重新打开播放器
        args = f'/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /DIR="{APP_DIR}" /relaunch=1'
        try:
            # 用 ShellExecute 启动：不继承播放器的句柄，安装目录需要管理员权限时也能弹 UAC
            os.startfile(setup, "open", args)
        except Exception as e:
            print(f"[update] 启动安装包失败：{e}", flush=True)
            self._set(state="available")
            self.toast.emit("启动安装程序失败，请到下载目录手动运行")
            return
        print(f"[update] 已启动安装包 {setup}", flush=True)
        self._set(state="installing", progress=1.0)
        self.quitRequested.emit()
