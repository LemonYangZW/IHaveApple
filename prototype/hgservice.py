"""hgservice — 把本地 SDK（ohgd）包装成 QML 可用的后端

职责：
  · 拉剧单与分集，组装成 QML 期望的 drama 结构
  · 按需解析播放地址（后台线程，不阻塞 UI）
  · 对服务端做预热与限流退避

QML 用法（注册为 context property `Backend`）：
    Backend.dramas                      // [{id, title, total, covers, desc}]
    Backend.prepare(dramaId, episode, definition, strict, seekable)   // 请求播放地址；definition 如 "720p"，"" = 默认
                                        // strict：只要这一档（换清晰度时用），否则本地已缓存的任意一档优先
                                        // seekable：要从中途起播，等这一集落盘再给地址
    signal episodeReady(dramaId, episode, url, definition)
    signal episodeFailed(dramaId, episode, reason, definition)
"""

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from queue import Empty, Queue

from PySide6.QtCore import Property, QCoreApplication, QObject, QSettings, QStandardPaths, Signal, Slot

HERE = os.path.dirname(os.path.abspath(__file__))
# 打包版（PyInstaller）：SDK 在 exe 旁边的 hgd/、ffmpeg 在 ffmpeg/；开发时用 hongguo 工程里的 SDK。
# 两种情况都可以用环境变量 IHAVEAPPLE_SDK 指定 SDK 目录
FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.path.dirname(sys.executable) if FROZEN else HERE
SDK_DIR = os.environ.get("IHAVEAPPLE_SDK") or (
    os.path.join(APP_DIR, "hgd") if FROZEN else os.path.join(HERE, "..", "..", "hongguo", "hgd"))
SDK_EXE = os.path.join(SDK_DIR, "ohgd.exe")
API = "http://127.0.0.1:8899"
QUALITY = "1080p"                 # 界面选「自动」（definition 为空）时用的清晰度
SWITCH_WAIT = 40                  # 播放中换清晰度时，最多等新清晰度落盘多久（秒）

# 顶部频道：三个 tab（顺序与界面一致）。后端 feed 用 channel 参数区分内容流，
# 实测「推荐」是混合推荐流，跟「真人剧」返回的不是同一批。
# 「AI剧」上游没有这个频道（unknown discover channel），已从 tab 隐藏。
CHANNELS = ("真人剧", "漫剧", "推荐")
DEFAULT_CHANNEL = "推荐"

# 缓存根目录：封面、推荐列表、视频缓存统一放在一棵树里，设置页可以整体换位置。
# 默认放在用户目录（安装目录可能不可写，也不该塞进程序目录）；IHAVEAPPLE_CACHE 供测试覆盖。
# 结构：<root>/covers（封面）、<root>/feeds（推荐列表）、<root>/video（ohgd 视频缓存）。
FEED_TTL = 30 * 60                # 缓存被认为「够新」的时长（秒）；过期仍可先用后刷
COVER_WIDTH = 480                 # 竖屏海报按窗口宽度出图，够清楚又不拖慢加载
_BUNDLED_FFMPEG = os.path.join(APP_DIR, "ffmpeg", "ffmpeg.exe")
FFMPEG = _BUNDLED_FFMPEG if FROZEN and os.path.exists(_BUNDLED_FFMPEG) else shutil.which("ffmpeg")
# 转码是 CPU 密集的 HEVC 解码，必须让着播放器（libmpv 是软渲染）：
# 低优先级 + 每路单线程。搜索结果一次要补十来张，2 路太慢，4 路低优先级实测不影响播放。
_COVER_NICE = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
COVER_WORKERS = 4

# 推荐池：一次 feed 单页（实测 9 部）全部收入，首屏从里面挑一部推荐。
# 不逐部预拉分集：feed 自带 episode_count，分集在真正要播时才拉（见 _prepare），
# 这样启动只花一次 feed 请求，比「4 部 × 每部拉分集」快得多。
FEED_MAX = 240        # 推荐流累积上限（每页 6 部，滚到末尾自动续页）
FEED_MORE_AT = 3      # 离末尾还剩几部时开始续页
# 分集一次全取（接口本身一次返回全部）；这个上限只是防御，免得异常数据撑爆内存
EPISODES_PER_SERIES = 800

# 封面占位色（内容占位，不是 UI 色板）
COVER_PAIRS = [
    ("#5B2333", "#C2595E"), ("#3C2A4D", "#B27BA8"),
    ("#1E2B38", "#4F7A94"), ("#4A3420", "#C9965A"),
]


def _default_cache_root():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "IHaveApple", "cache")


def _cache_root_from_settings():
    """缓存目录：IHAVEAPPLE_CACHE > 设置页保存的值 > 用户目录下的默认位置。"""
    env = os.environ.get("IHAVEAPPLE_CACHE") or ""
    if env:
        return os.path.abspath(os.path.expanduser(env))
    try:
        saved = QSettings().value("cache/dir", "", type=str)
    except Exception:
        saved = ""
    if saved:
        return os.path.abspath(os.path.expanduser(saved))
    return _default_cache_root()


def current_cache_root():
    return _cache_root_from_settings()


def video_cache_dir():
    return os.path.join(current_cache_root(), "video")


def cover_cache_dir():
    return os.path.join(current_cache_root(), "covers")


def feed_cache_dir():
    return os.path.join(current_cache_root(), "feeds")


def danmaku_cache_dir():
    return os.path.join(current_cache_root(), "danmaku")


def _cache_subdirs(root):
    return (os.path.join(root, "covers"),
            os.path.join(root, "feeds"),
            os.path.join(root, "video"),
            os.path.join(root, "danmaku"))


def _ensure_cache_dirs(root):
    for d in (root,) + _cache_subdirs(root):
        os.makedirs(d, exist_ok=True)


def _dir_size(root):
    total = 0
    for base, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


def _fmt_bytes(n):
    n = float(max(0, n))
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _path_from_input(text):
    """设置页选出来的可能是 file:///D:/... 也可能是普通路径。"""
    s = (text or "").strip()
    if s.startswith("file:"):
        p = urllib.parse.urlparse(s).path
        if os.name == "nt" and len(p) > 2 and p[0] == "/" and p[2] == ":":
            p = p[1:]
        return os.path.abspath(os.path.expanduser(urllib.parse.unquote(p)))
    return os.path.abspath(os.path.expanduser(s))


class AnonLimited(Exception):
    """上游对匿名设备关闭了数据通道（返回空体）。

    这是上游的反爬额度，重试不会恢复，必须立刻失败并给出人话提示。
    """


def _api(path, timeout=40, tries=4, gap=2.5):
    last = None
    for _ in range(tries):
        try:
            with urllib.request.urlopen(API + path, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            # 额度类错误重试多少次都一样，直接抛出去让上层给提示
            if "anonymous response was empty" in body or "rate limited" in body:
                raise AnonLimited(body) from None
            last = e
            time.sleep(gap)
        except Exception as e:
            last = e
            time.sleep(gap)
    raise last


def _file_url(path):
    return "file:///" + os.path.abspath(path).replace("\\", "/")


def _cover_file(drama_id, url, cover_dir):
    """下载封面并转成本地 JPEG，返回 file:/// 地址；失败返回 ""（QML 退回占位渐变）。

    服务端给的是 HEIC，Qt 自己解不了：先用 ftyp 盒子判断格式，HEIC 走 ffmpeg 转码。
    转码结果按剧 id 缓存，同一部剧只解码一次。
    """
    if not url:
        return ""
    out = os.path.join(cover_dir, f"{drama_id}.jpg")
    if os.path.exists(out) and os.path.getsize(out) > 1024:
        return _file_url(out)
    os.makedirs(cover_dir, exist_ok=True)
    tmp = os.path.join(cover_dir, f".{drama_id}.dl")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as e:
        print(f"[sdk] cover download failed {drama_id}: {e}", flush=True)
        return ""
    try:
        with open(tmp, "rb") as f:
            head = f.read(16)
        is_heic = b"ftyphei" in head or b"ftypmif1" in head or url.lower().endswith(".heic")
        if is_heic:
            if not FFMPEG:
                print("[sdk] 找不到 ffmpeg，封面无法转码（界面退回占位渐变）", flush=True)
                return ""
            subprocess.run(
                [FFMPEG, "-y", "-loglevel", "error", "-threads", "1", "-i", tmp,
                 "-frames:v", "1", "-vf", f"scale={COVER_WIDTH}:-2", "-q:v", "5", out],
                check=True, timeout=60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | _COVER_NICE,
            )
        else:
            os.replace(tmp, out)      # 已经是 JPEG，直接用
    except Exception as e:
        print(f"[sdk] cover transcode failed {drama_id}: {e}", flush=True)
        return ""
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return _file_url(out) if os.path.exists(out) else ""


def _poster_path(eid, cover_dir):
    return os.path.join(cover_dir, f"ep_{eid}.jpg")


def _make_poster(eid, definition, video_dir, cover_dir):
    """从已落盘的 mp4 抽出这一集的第一帧，存成 JPEG（已有就跳过）。返回是否可用。

    切集时先显示它而不是剧封面：起播后画面从同一帧接上，看不出两集之间的加载。
    原分辨率出图：比视频糊的话，起播那一下能看出画面「变清楚」。
    """
    out = _poster_path(eid, cover_dir)
    if os.path.exists(out) and os.path.getsize(out) > 1024:
        return True
    if not FFMPEG:
        return False
    # ohgd 缓存优先：落盘的可能不是请求的那一档，优先同档，没有就取任意一档
    exact = os.path.join(video_dir, f"{eid}_{definition}.mp4")
    if os.path.exists(exact):
        src = exact
    else:
        src = next((os.path.join(video_dir, f) for f in os.listdir(video_dir)
                    if f.startswith(eid + "_") and f.endswith(".mp4")), "")
    if not src:
        return False
    tmp = os.path.join(cover_dir, f".ep_{eid}.tmp.jpg")
    try:
        subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error", "-threads", "1", "-i", src,
             "-frames:v", "1", "-q:v", "3", tmp],
            check=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | _COVER_NICE,
        )
        os.replace(tmp, out)
        return True
    except Exception as e:
        print(f"[sdk] 首帧抽取失败 {eid}: {e}", flush=True)
        return False
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _wait_cached(eid, definition, timeout=SWITCH_WAIT):
    """换清晰度：等 SDK 把这一档落盘（3–8 秒）。

    没落盘时 /v1/stream 是实时转封装的流，不能 seek，只能从头播，接不上原位置；
    落盘后同一个地址就是普通 mp4，可以从原位置起播。等待期间原画面照常播放。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = _api(f"/v1/cache/prewarm/{eid}?definition={definition}", timeout=60, tries=1)
        if r.get("state") == "ready":
            return
        time.sleep(1.0)
    raise TimeoutError("新清晰度准备超时")


def _url_definition(url, fallback):
    """播放地址里实际的清晰度（缓存优先时可能和请求的不同）"""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return (q.get("definition") or [fallback])[0]


def _url_key(definition, strict):
    """播放地址缓存的键：同一清晰度的 strict / 非 strict 请求可能拿到不同的地址"""
    return f"{definition}!" if strict else definition


def _kill_with_parent(proc):
    """把 ohgd 挂进 Job Object（KILL_ON_JOB_CLOSE），让子进程跟着播放器一起收走。

    正常退出由 shutdown() 的 terminate() 负责；这里补的是异常退出——被任务管理器
    结束、崩溃、taskkill /F 时 Python 一行清理代码都跑不到，只有 Job 句柄随进程
    关闭时由内核结束子进程。挂不上（比如被外层 Job 限制）就返回 None，行为退回原样。
    """
    if os.name != "nt" or proc is None:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None

        class _Basic(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _Io(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class _Extended(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _Basic),
                ("IoInfo", _Io),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = _Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(job)
            return None
        if not k32.AssignProcessToJobObject(job, int(proc._handle)):
            k32.CloseHandle(job)
            return None
        return job
    except Exception:
        return None


class HgService(QObject):
    dramasChanged = Signal()
    episodeReady = Signal(str, int, str, str) # dramaId, episode(0-based), url, definition（与请求时一致）
    episodeFailed = Signal(str, int, str, str) # dramaId, episode, reason, definition
    statusChanged = Signal()
    channelChanged = Signal()
    toast = Signal(str)
    searchResults = Signal(str, list)         # query, [{id,title,total,covers,desc}]
    cacheChanged = Signal()                   # 缓存目录 / 占用 / 忙闲状态变了
    postersChanged = Signal()                 # 有新的首帧图（或缓存目录换了 / 清空了）
    danmakuLoaded = Signal(str, int)          # dramaId, episode(0 起)：这一集的弹幕到了
    resetRequested = Signal()                 # 完全重置：界面退出程序，退出后由 main.py 清理并重启

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dramas = []
        # 剧单之外认识的剧（观看历史里的、搜过的）：id -> 剧单条目。
        # 切频道 / 刷新时剧单整个换成新频道的，这些要接在后面，历史和搜索结果才解析得到
        self._known = {}
        self._episodes = {}      # dramaId -> [ {id, number, label, duration, url, state} ]
        self._fetching = set()   # 正在拉分集的剧 id（避免同一部并发拉两次）
        self._lock = threading.Lock()
        self._status = "idle"
        self._proc = None
        self._job = None       # Job Object 句柄：崩溃时由内核收走 ohgd
        self._recommend = ""     # 首屏推荐（每次启动换一部）
        self._channel = self._saved_channel()
        self._feed_cache = {}    # channel -> {items, ts}；有它切频道就不用等 4–5 秒
        self._feed_inflight = {} # channel -> Event：同频道的并发请求合并成一次
        self._more_inflight = set()  # 正在续页的频道（同一频道只续一次，避免连点叠请求）
        self._refresh_inflight = set()  # 正在「换一批」的频道（连点 tab 时只发一次请求）
        self._warming = False    # 是否已有预热线程在跑（避免重复预热）
        self._covering = False   # 是否已有封面补全在跑（避免两批抢同一批剧）
        self._cover_again = False  # 期间又有新剧要补，等当前批结束后再来一轮
        self._channel_last = {}  # channel -> 上次在该频道看的剧，切回来直接回到这部
        self._feed_ids = []      # 当前频道 feed 的剧 id 顺序（不含搜索并入的剧，滚动换剧按它走）
        self._prefetched = set() # (dramaId, ep, definition) 已排队预取的集，避免重复请求
        self._danmaku = {}       # (dramaId, episodeId) -> [{id,text,offset,likes}]，内存缓存
        self._danmaku_fetching = set()  # 正在翻页拉的 (dramaId, episodeId)
        self._preload_queue = [] # 预载队列 [(dramaId, ep, definition)]，按播放页给的顺序逐个落盘
        self._preloading = False # 预载线程是否在跑
        self._poster_rev = 0     # 首帧图版本号：QML 绑定读它，有新图时 +1 让 posterOf 重新求值
        self.reset_requested = False   # 设置页点了「完全重置」：main.py 在退出后清理并重启
        self._current_drama = "" # 最近一次准备播放的剧（用于记录 _channel_last）
        # 缓存位置（设置页可改）：封面、推荐列表、视频各一个子目录
        self._cache_root = _cache_root_from_settings()
        try:
            _ensure_cache_dirs(self._cache_root)
        except Exception as e:
            print(f"[sdk] 缓存目录不可用（{self._cache_root}）：{e}，改用默认目录", flush=True)
            self._cache_root = _default_cache_root()
            _ensure_cache_dirs(self._cache_root)
        (self._cover_dir, self._feed_dir, self._video_dir,
         self._danmaku_dir) = _cache_subdirs(self._cache_root)
        self._cache_busy = False
        self._cache_size_text = ""
        self._load_feed_cache()
        self.refreshCacheSize()

    # ---------- 生命周期 ----------
    def ensure_service(self):
        if self._alive():
            return
        if not os.path.exists(SDK_EXE):
            self._status = "error"
            self.toast.emit(f"找不到 SDK：{SDK_EXE}")
            return
        try:
            cmd = [SDK_EXE, "-addr", "127.0.0.1:8899", "-cache", os.path.abspath(self._video_dir)]
            if FROZEN and FFMPEG:
                cmd += ["-ffmpeg", FFMPEG]      # 打包版用自带的 ffmpeg（开发时按 SDK 的 config.json）
            self._proc = subprocess.Popen(
                cmd,
                cwd=SDK_DIR,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._job = _kill_with_parent(self._proc)
        except Exception as e:
            self._status = "error"
            self.toast.emit(f"SDK 启动失败：{e}")
            return
        for _ in range(80):
            if self._alive():
                return
            time.sleep(0.5)
        self._status = "error"
        self.toast.emit("SDK 启动超时")

    def _alive(self):
        try:
            with urllib.request.urlopen(API + "/v1/health", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def _stop_service(self, wait=True):
        """停掉 ohgd（换缓存目录 / 清缓存前必须先停，否则文件被占用）。"""
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
            if wait:
                try:
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=3)
                    except Exception:
                        pass
        job, self._job = self._job, None
        if job:
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(job)
            except Exception:
                pass

    def shutdown(self):
        self._stop_service(wait=False)

    # ---------- 数据 ----------
    @Property(list, notify=dramasChanged)
    def dramas(self):
        return self._dramas

    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    # ---------- 频道（顶部 tab） ----------
    @Property(str, notify=channelChanged)
    def channel(self):
        return self._channel

    @Property(list, constant=True)
    def channels(self):
        return list(CHANNELS)

    def _saved_channel(self):
        try:
            ch = QSettings().value("feed/channel", DEFAULT_CHANNEL, type=str)
        except Exception:
            ch = DEFAULT_CHANNEL
        return ch if ch in CHANNELS else DEFAULT_CHANNEL

    @Slot(str)
    def set_channel(self, ch):
        """切换频道：有本地缓存就立刻出画面，同时后台静默刷新。"""
        ch = (ch or "").strip()
        if ch not in CHANNELS or ch == self._channel:
            return
        # 记住离开的频道正在看的剧，切回来时直接回到这部（像切 tab 回到上次位置）
        if self._current_drama and self._channel:
            self._channel_last[self._channel] = self._current_drama
            self._save_feed_cache(self._channel)
        self._channel = ch
        try:
            QSettings().setValue("feed/channel", ch)
        except Exception:
            pass
        self.channelChanged.emit()
        print(f"[sdk] 切换频道 -> {ch}", flush=True)

        entry = self._feed_cache.get(ch)
        if entry is not None:
            # 命中缓存就立即出画面；空频道（items 为空）也一样，不用再等请求超时
            age = time.time() - entry.get("ts", 0)
            print(f"[sdk] {ch} 命中本地缓存（{age / 60:.0f} 分钟前），立即出画面", flush=True)
            self._apply_items(ch, entry.get("items") or [], self._channel_last.get(ch, ""),
                              random_fallback=False)
            threading.Thread(target=self._refresh_channel, args=(ch,), daemon=True).start()
            return

        with self._lock:
            self._dramas = []        # 无缓存：先清空，界面立刻离开上一频道的剧
            self._recommend = ""
        self._status = "loading"
        self.dramasChanged.emit()
        self.statusChanged.emit()
        self.load_async(ch)

    # 首屏推荐：每次启动换一部（排除上次推荐过的那部），QML 用它决定首屏播放哪部
    @Property(str, notify=dramasChanged)
    def recommendId(self):
        return self._recommend

    # 当前频道 feed 的顺序（滚动换剧用）。搜索结果只并入 dramas，不改变这个顺序。
    @Property(list, notify=dramasChanged)
    def feedIds(self):
        return self._feed_ids

    # 推荐流还能不能继续往后续页（滚动到末尾附近时 QML 据此提前拉下一页）
    @Property(bool, notify=dramasChanged)
    def feedHasMore(self):
        entry = self._feed_cache.get(self._channel) or {}
        return bool(entry.get("has_more")) and len(entry.get("items") or []) < FEED_MAX

    # 离末尾还剩几部时开始续页（QML 用这个值判断，前后端口径一致）
    @Property(int, constant=True)
    def feedMoreAt(self):
        return FEED_MORE_AT

    @Slot()
    def ensureCovers(self):
        """补齐所有剧的封面。启动时只转前几张，打开搜索 / 历史页面时再补齐剩下的。"""
        self._backfill_covers_async()

    def load_async(self, channel=None):
        """启动加载：有本地缓存就先出画面，再后台刷新（首屏不再干等 4–5 秒）。"""
        ch = channel if channel is not None else self._channel
        entry = self._feed_cache.get(ch)
        # 上次停在没内容的频道（比如点过 AI剧 就关窗口）：别让首屏一片空白，回退默认频道
        if channel is None and entry is not None and not (entry.get("items") or []):
            print(f"[sdk] 上次的频道「{ch}」没有内容，首屏回退到「{DEFAULT_CHANNEL}」", flush=True)
            self._channel = DEFAULT_CHANNEL
            try:
                QSettings().setValue("feed/channel", DEFAULT_CHANNEL)
            except Exception:
                pass
            self.channelChanged.emit()
            ch = DEFAULT_CHANNEL
            entry = self._feed_cache.get(ch)
        if entry is not None:
            print(f"[sdk] {ch} 用本地缓存先出画面（{len(entry.get('items') or [])} 部）", flush=True)
            self._apply_items(ch, entry.get("items") or [], "", random_fallback=True)
            threading.Thread(target=self._refresh_channel, args=(ch,), daemon=True).start()
            self.warm_channels_async()
            return
        threading.Thread(target=self._load, args=(ch, channel is None), daemon=True).start()

    # ---------- 缓存 ----------
    def _cache_path(self, ch):
        return os.path.join(self._feed_dir, ch + ".json")

    def _load_feed_cache(self):
        """启动时把上次的 feed 缓存读进内存（含每个频道上次看的剧）。"""
        try:
            os.makedirs(self._feed_dir, exist_ok=True)
        except Exception:
            return
        for ch in CHANNELS:
            p = self._cache_path(ch)
            if not os.path.exists(p):
                continue
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                items = d.get("items") or []
                # 空 items 也缓存：无内容的频道（AI剧）不该每次切过去都等一次请求
                self._feed_cache[ch] = {"items": items, "ts": float(d.get("ts") or 0),
                                        "cursor": str(d.get("cursor") or ""),
                                        "has_more": bool(d.get("has_more"))}
                if d.get("last"):
                    self._channel_last[ch] = str(d["last"])
            except Exception as e:
                print(f"[sdk] feed 缓存读取失败 {ch}: {e}", flush=True)

    def _save_feed_cache(self, ch):
        entry = self._feed_cache.get(ch)
        if not entry:
            return
        try:
            os.makedirs(self._feed_dir, exist_ok=True)
            tmp = self._cache_path(ch) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"items": entry["items"], "ts": entry["ts"],
                           "cursor": entry.get("cursor", ""),
                           "has_more": bool(entry.get("has_more")),
                           "last": self._channel_last.get(ch, "")}, f, ensure_ascii=False)
            os.replace(tmp, self._cache_path(ch))
        except Exception as e:
            print(f"[sdk] feed 缓存写入失败 {ch}: {e}", flush=True)

    # ---------- 缓存目录与清理（设置页） ----------
    @Property(str, notify=cacheChanged)
    def cacheDir(self):
        return self._cache_root

    @Property(str, notify=cacheChanged)
    def cacheSizeText(self):
        return self._cache_size_text or "计算中…"

    @Property(bool, notify=cacheChanged)
    def cacheBusy(self):
        return self._cache_busy

    @Slot()
    def refreshCacheSize(self):
        """后台统计缓存占用（视频缓存可能有几个 GB，别在 UI 线程里 walk）。"""
        root = self._cache_root

        def work():
            size = _dir_size(root)
            if root != self._cache_root:
                return                      # 统计期间换了目录，这批结果作废
            self._cache_size_text = _fmt_bytes(size)
            self.cacheChanged.emit()

        threading.Thread(target=work, daemon=True).start()

    @Slot()
    def chooseCacheDir(self):
        """弹系统目录选择框；选中后切换缓存位置。"""
        if self._cache_busy:
            return
        try:
            from PySide6.QtWidgets import QApplication, QFileDialog
            parent = QApplication.activeWindow()
            path = QFileDialog.getExistingDirectory(parent, "选择缓存目录", self._cache_root)
        except Exception as e:
            self.toast.emit(f"打开目录选择失败：{e}")
            return
        if path:
            self.setCacheDir(path)

    @Slot(str)
    def setCacheDir(self, path):
        if self._cache_busy:
            return
        new = _path_from_input(str(path))
        if not new:
            return
        if os.path.abspath(new) == os.path.abspath(self._cache_root):
            self.toast.emit("缓存已经在这个目录")
            return
        # 先确认目录可写：外部磁盘 / 受保护目录直接拒绝，别等播放时才炸
        try:
            _ensure_cache_dirs(new)
            probe = os.path.join(new, ".write-test")
            with open(probe, "wb") as f:
                f.write(b"ok")
            os.remove(probe)
        except Exception as e:
            self.toast.emit(f"这个目录不能用：{e}")
            return
        try:
            QSettings().setValue("cache/dir", new)
        except Exception:
            pass
        self._cache_busy = True
        self.cacheChanged.emit()
        threading.Thread(target=self._switch_cache_dir, args=(new,), daemon=True).start()

    def _switch_cache_dir(self, new):
        try:
            self._stop_service()            # ohgd 还握着旧目录里的视频文件
            self._cache_root = new
            (self._cover_dir, self._feed_dir, self._video_dir,
             self._danmaku_dir) = _cache_subdirs(new)
            with self._lock:
                self._feed_cache.clear()
                self._danmaku.clear()        # 弹幕缓存跟着目录走，换目录后重新拉
                for d in self._dramas:
                    d["cover"] = ""          # 旧目录的封面不再引用，回占位后重新补
                    d["cover_tried"] = False
            self._load_feed_cache()
            self.dramasChanged.emit()
            self._bump_posters()             # 首帧图跟着缓存目录走，换目录后重新查
            self._backfill_covers_async(limit=20)
            print(f"[sdk] 缓存目录 -> {new}", flush=True)
            self.toast.emit("缓存目录已切换；旧目录里的文件不会自动删除")
        except Exception as e:
            self.toast.emit(f"切换缓存目录失败：{e}")
        finally:
            self._cache_busy = False
            self.refreshCacheSize()
            self.cacheChanged.emit()

    @Slot()
    def clearCache(self):
        """清空当前缓存目录。会先停 ohgd：视频文件被占用时 Windows 删不掉。"""
        if self._cache_busy:
            return
        self._cache_busy = True
        self.cacheChanged.emit()
        threading.Thread(target=self._clear_cache, daemon=True).start()

    def _clear_cache(self):
        before = _dir_size(self._cache_root)
        try:
            self._stop_service()
            with self._lock:
                self._danmaku.clear()          # 文件删了，内存里的也不再引用
            for name in os.listdir(self._cache_root):
                p = os.path.join(self._cache_root, name)
                try:
                    if os.path.isdir(p) and not os.path.islink(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        os.remove(p)
                except OSError as e:
                    print(f"[sdk] 缓存删除失败 {p}: {e}", flush=True)
            _ensure_cache_dirs(self._cache_root)
            after = _dir_size(self._cache_root)   # 先量，再补封面，免得把新图算进去
            with self._lock:
                for d in self._dramas:
                    d["cover"] = ""
                    d["cover_tried"] = False
            self.dramasChanged.emit()
            self._bump_posters()                  # 首帧图已删，界面退回剧封面
            self._backfill_covers_async(limit=20)
            freed = max(0, before - after)
            msg = f"已清理缓存，释放 {_fmt_bytes(freed)}"
            if after > 0:
                msg += f"；还有 {_fmt_bytes(after)} 被占用，退出后会自动释放"
            self.toast.emit(msg)
            print(f"[sdk] 清理缓存：{_fmt_bytes(before)} -> {_fmt_bytes(after)}", flush=True)
        except Exception as e:
            self.toast.emit(f"清理缓存失败：{e}")
        finally:
            self._cache_busy = False
            self.refreshCacheSize()
            self.cacheChanged.emit()

    # ---------- 完全重置 ----------
    @Slot()
    def resetAll(self):
        """设置页「完全重置」：先让界面退出，真正的清理在退出后由 main.py 调 wipe_all()。
        不能在运行中清：QML 的 Settings 析构时会把没写完的值刷回注册表，清了也会被写回来。"""
        self.reset_requested = True
        self.resetRequested.emit()

    def wipe_all(self):
        """删除本软件的所有缓存和数据：设置、观看历史、搜索记录（注册表）、封面 / 推荐列表 / 视频缓存、
        首帧图、QML 编译缓存、下载的更新安装包，以及片源服务的匿名设备身份。调用前 QML 引擎必须已销毁。"""
        self._stop_service()                # ohgd 握着视频文件和身份文件
        dirs = [_default_cache_root()]
        root = os.path.normcase(os.path.abspath(self._cache_root))
        if root != os.path.normcase(os.path.abspath(_default_cache_root())):
            # 自选的缓存目录里可能有用户自己的文件：只删我们建的三个子目录
            dirs += list(_cache_subdirs(self._cache_root))
        app_data = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
        if app_data and os.path.basename(os.path.normpath(app_data)) == QCoreApplication.applicationName():
            dirs.append(app_data)           # QML 编译缓存等；名字对不上（应用名没设）就不删，免得删到上级目录
        dirs.append(os.path.join(tempfile.gettempdir(), "IHaveApple-update"))
        files = []
        if FROZEN:
            # 安装版：程序目录下片源服务的缓存和匿名身份（开发时 SDK 目录是另一个工程，不碰）
            dirs += [os.path.join(SDK_DIR, "cache"), os.path.join(APP_DIR, ".cache"),
                     os.path.join(APP_DIR, "_internal", ".cache")]
            if os.path.isdir(SDK_DIR):
                files += [os.path.join(SDK_DIR, f) for f in os.listdir(SDK_DIR)
                          if (f.startswith("anonymous") and f.endswith(".json")) or f == "actor_id.txt"]
        for d in dirs:
            if d and os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
        for f in files:
            try:
                os.remove(f)
            except OSError as e:
                print(f"[sdk] 重置时删除失败 {f}: {e}", flush=True)
        s = QSettings()
        s.clear()
        s.sync()
        print("[sdk] 已完全重置：" + "；".join(dirs + files), flush=True)

    def _fetch_feed(self, ch, cursor=""):
        """请求 feed 的一页，返回 (items, cursor, has_more)。

        cursor 为空是第一页；续页把它原样带回去（服务端游标，不能自己拼）。
        空频道（上游不认）返回 ([], "", False)，其他错误抛出。
        """
        path = "/v1/feed?channel=" + urllib.parse.quote(ch)
        if cursor:
            path += "&cursor=" + urllib.parse.quote(cursor)
        try:
            # feed 一次要 4–5 秒，重试 4 次会把「无内容频道」拖成 9 秒；
            # 只重试一次，失败交给上层用缓存兜底
            feed = _api(path, timeout=30, tries=2, gap=1.0)
        except Exception as e:
            # 上游没有这个频道（实测 AI剧 返回 502 unknown discover channel）：
            # 不是故障，按「暂无内容」处理
            try:
                if isinstance(e, urllib.error.HTTPError) and e.code == 502:
                    if "unknown discover channel" in e.read().decode("utf-8", "replace"):
                        return [], "", False
            except Exception:
                pass
            raise
        return feed.get("items") or [], feed.get("cursor") or "", bool(feed.get("has_more"))

    def _fetch_feed_shared(self, ch):
        """同一个频道只发一次请求：预热和用户切换撞在一起时，后者等前者的结果。

        feed 一次要 4–5 秒，重复请求会让「第一次切频道」多等一倍。
        """
        with self._lock:
            ev = self._feed_inflight.get(ch)
            if ev is not None:
                owner = False
            else:
                ev = threading.Event()
                self._feed_inflight[ch] = ev
                owner = True
        if not owner:
            ev.wait(40)
            with self._lock:
                entry = self._feed_cache.get(ch)
            return (entry or {}).get("items") or []
        try:
            items, cursor, has_more = self._fetch_feed(ch)
            with self._lock:
                old_items = (self._feed_cache.get(ch) or {}).get("items") or []
                if old_items:
                    # 刷新时保留已经续过的页：新首页排在最前，旧的按原顺序接在后面
                    seen = {s.get("id") for s in items}
                    items = (items + [s for s in old_items if s.get("id") not in seen])[:FEED_MAX]
                self._feed_cache[ch] = {"items": items, "ts": time.time(),
                                        "cursor": cursor, "has_more": bool(has_more)}
            self._save_feed_cache(ch)
            return items
        finally:
            with self._lock:
                self._feed_inflight.pop(ch, None)
            ev.set()

    # ---------- 推荐流续页 ----------
    @Slot()
    def loadMore(self):
        """QML：离推荐流末尾不远了，后台续一页（不阻塞画面）。"""
        threading.Thread(target=self._more, daemon=True).start()

    def _more(self, channel=None):
        """往当前频道的推荐流末尾续一页。

        服务端游标会随会话 / 时间失效：失败时保留游标下次再试，成功后换成新游标。
        重复的剧按 id 去掉（实测相邻页会有重叠），只追加新的。
        """
        ch = channel if channel is not None else self._channel
        with self._lock:
            entry = self._feed_cache.get(ch)
            if not entry or not entry.get("has_more") or not entry.get("cursor"):
                return
            if ch in self._more_inflight:
                return
            self._more_inflight.add(ch)
        try:
            self.ensure_service()
            page, next_cursor, has_more = self._fetch_feed(ch, entry.get("cursor") or "")
            with self._lock:
                entry = self._feed_cache.get(ch) or entry    # 期间可能被后台刷新换成了新字典
                known = {s.get("id") for s in (entry.get("items") or [])}
                fresh = [s for s in page if s.get("id") and s.get("id") not in known]
                entry["items"] = ((entry.get("items") or []) + fresh)[:FEED_MAX]
                entry["cursor"] = next_cursor
                entry["has_more"] = bool(has_more) and len(entry["items"]) < FEED_MAX
                entry["ts"] = time.time()
                add = []
                if ch == self._channel:
                    have = {d["id"] for d in self._dramas}
                    for s in fresh:
                        if s["id"] in self._feed_ids:
                            continue
                        self._feed_ids.append(s["id"])
                        if s["id"] not in have:
                            add.append(self._to_drama(s, len(self._feed_ids) - 1))
                    if add:
                        self._dramas = self._dramas + add
                total = len(entry["items"])
            self._save_feed_cache(ch)
            print(f"[sdk] {ch} 续页 +{len(fresh)} 部，累计 {total} 部"
                  f"（has_more={entry['has_more']}）", flush=True)
            if ch == self._channel and fresh:
                self.dramasChanged.emit()
                self._backfill_covers_async(limit=3)
        except Exception as e:
            print(f"[sdk] {ch} 续页失败（保留游标，稍后再试）: {e}", flush=True)
        finally:
            with self._lock:
                self._more_inflight.discard(ch)

    # ---------- 再点一次当前频道：换一批 ----------
    @Slot()
    def reshuffle(self):
        """QML：再点一次当前频道 tab，换一批节目（后台重新拉首页，合并进现有列表）。"""
        threading.Thread(target=self._reshuffle, daemon=True).start()

    def _reshuffle(self, channel=None):
        """重新拉当前频道首页，把新的一批排到最前，同时保留旧列表（正在看的剧不会掉出剧单）。"""
        ch = channel if channel is not None else self._channel
        with self._lock:
            if ch in self._refresh_inflight:
                return
            self._refresh_inflight.add(ch)
        try:
            self.ensure_service()
            page, cursor, has_more = self._fetch_feed(ch)
            if not page:
                self.toast.emit(f"{ch} · 上游暂时没有新内容")
                return
            with self._lock:
                entry = self._feed_cache.get(ch) or {}
                old = entry.get("items") or []
                old_ids = {s.get("id") for s in old}
                page_ids = {s.get("id") for s in page}
                merged = (page + [s for s in old if s.get("id") not in page_ids])[:FEED_MAX]
                fresh = len([s for s in page if s.get("id") not in old_ids])
                self._feed_cache[ch] = {"items": merged, "ts": time.time(),
                                        "cursor": cursor, "has_more": bool(has_more)}
            self._save_feed_cache(ch)
            if ch != self._channel:
                return                      # 请求期间切走了，缓存更新即可
            # 正在看的这部还在这批里就继续选它（QML 已经先换到别的剧了，这里只重排剧单）
            self._apply_items(ch, merged, prefer=self._current_drama, random_fallback=False)
            self.toast.emit(f"{ch} · 已换一批（新增 {fresh} 部）" if fresh
                            else f"{ch} · 这一批没有新节目，再点一次试试")
            print(f"[sdk] {ch} 换一批：新增 {fresh} 部，累计 {len(merged)} 部", flush=True)
        except Exception as e:
            print(f"[sdk] {ch} 换一批失败: {e}", flush=True)
            self.toast.emit(f"{ch} · 换一批失败，稍后再试")
        finally:
            with self._lock:
                self._refresh_inflight.discard(ch)

    @staticmethod
    def _to_drama(s, i):
        """feed 里的一条 → QML 用的剧单条目。i 只用于给列表配色 / 占位渐变。"""
        return {
            "id": s["id"],
            "title": s.get("title", ""),
            # feed 自带真实集数；不再为拿集数而预拉分集（那会让启动慢好几秒）
            "total": s.get("episode_count", 0),
            "covers": list(COVER_PAIRS[i % len(COVER_PAIRS)]),
            "cover": "",                      # 本地转码后的封面，后台补
            "cover_url": s.get("cover_url", ""),
            "desc": s.get("description", ""),
        }

    def _apply_items(self, ch, items, prefer="", random_fallback=True):
        """把 feed items 变成 QML 用的剧单并发出信号。prefer：优先播哪部。

        items 是缓存里累积的整段推荐流（首页 + 已续过的页），滚动到末尾会继续追加。
        """
        out = [self._to_drama(s, i) for i, s in enumerate(items[:FEED_MAX])]
        ids = [d["id"] for d in out]
        if prefer and prefer in ids:
            rec = prefer                          # 切回频道：回到上次看的那部
        elif random_fallback:
            rec = self._pick_recommend(out)       # 启动：每次换一部
        else:
            rec = ids[0] if ids else ""
        with self._lock:
            # 历史 / 搜索认识的剧接在频道剧单后面（滚动换剧只按 _feed_ids 走，不受影响）
            in_feed = set(ids)
            self._dramas = out + [d for sid, d in self._known.items() if sid not in in_feed]
            self._recommend = rec
            self._feed_ids = list(ids)
        print(f"[sdk] feed ready: {len(out)} 部（{ch}），推荐 {rec}", flush=True)
        # 空频道（如 AI剧 上游暂无内容）不算错误，界面显示「暂无内容」
        self._status = "ready" if out else "empty"
        self.dramasChanged.emit()
        self.statusChanged.emit()
        if out:
            self._backfill_covers_async(limit=3)     # 先转首屏这几张，其余打开面板时再补
            entry = self._feed_cache.get(ch) or {}
            if entry.get("has_more") and entry.get("cursor"):
                # 首页到手就先续一页：用户滑到末尾时，下一页通常已经在本地了
                threading.Thread(target=self._more, args=(ch,), daemon=True).start()
        return out

    def _load(self, channel=None, startup=False):
        """网络拉 feed（无缓存时的首次加载）。startup=True 表示这是启动加载。"""
        ch = channel if channel is not None else self._channel
        self._status = "loading"
        self.statusChanged.emit()
        try:
            self.ensure_service()
            items = self._fetch_feed_shared(ch)
        except Exception as e:
            if ch != self._channel:
                return                      # 请求期间已经切走，丢弃
            if ch in self._feed_cache:      # 有旧缓存就继续用，别把界面清空
                print(f"[sdk] {ch} 刷新失败，沿用缓存: {e}", flush=True)
                return
            self._status = "error"
            self.statusChanged.emit()
            self.toast.emit(f"拉取剧单失败：{e}")
            return
        if ch != self._channel:
            return                          # 期间切了频道，这批数据不要了

        # 启动时发现记住的频道没有内容（如上次停在 AI剧）：回退默认频道，别让首屏空白
        if startup and not items and ch != DEFAULT_CHANNEL:
            print(f"[sdk] 频道「{ch}」没有内容，首屏回退到「{DEFAULT_CHANNEL}」", flush=True)
            self._channel = DEFAULT_CHANNEL
            try:
                QSettings().setValue("feed/channel", DEFAULT_CHANNEL)
            except Exception:
                pass
            self.channelChanged.emit()
            self._load(DEFAULT_CHANNEL, False)
            return

        # 启动路径：首屏每次换一部（不用 _channel_last，那是「切频道回到上次」才用的）
        self._apply_items(ch, items, "", random_fallback=True)
        if items:
            self.toast.emit(f"{ch} · 已载入 {min(len(items), FEED_MAX)} 部剧")
        self.warm_channels_async()

    def _refresh_channel(self, ch):
        """后台静默刷新缓存：只更新缓存，不动正在显示/播放的内容（下次切换生效）。"""
        try:
            self.ensure_service()
            self._fetch_feed_shared(ch)
            print(f"[sdk] {ch} 缓存已刷新（下次切换生效）", flush=True)
        except Exception as e:
            print(f"[sdk] {ch} 后台刷新失败: {e}", flush=True)

    def warm_channels_async(self):
        with self._lock:
            if self._warming:
                return
            self._warming = True
        threading.Thread(target=self._warm_channels, daemon=True).start()

    def _warm_channels(self):
        """后台把其余频道的 feed 预先拉好放进缓存，第一次切也能秒开。

        2 路并行：太高的并发容易被上游限流，串行又要十几秒才轮完。
        """
        try:
            todo = []
            for ch in CHANNELS:
                if ch == self._channel:
                    continue
                entry = self._feed_cache.get(ch)
                if entry is not None and time.time() - entry.get("ts", 0) < FEED_TTL:
                    continue
                todo.append(ch)
            if not todo:
                return
            q = Queue()
            for ch in todo:
                q.put(ch)

            def worker():
                while True:
                    try:
                        ch = q.get_nowait()
                    except Empty:
                        return
                    try:
                        self.ensure_service()
                        items = self._fetch_feed_shared(ch)
                        print(f"[sdk] 预热 {ch}: {len(items)} 部", flush=True)
                    except Exception as e:
                        print(f"[sdk] 预热 {ch} 失败: {e}", flush=True)

            threads = [threading.Thread(target=worker, daemon=True)
                       for _ in range(min(2, len(todo)))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()      # 等这一轮全部结束再放开 _warming，否则会被重复触发
        finally:
            with self._lock:
                self._warming = False

    def _pick_recommend(self, dramas):
        """首屏推荐：像推荐流一样每次启动换一部，先排除上次看过的那部。

        feed 的顺序对同一台设备基本固定，所以「每次都是同一部」必须靠客户端轮换。
        """
        ids = [d["id"] for d in dramas]
        if not ids:
            return ""
        try:
            last = QSettings().value("feed/lastRecommend", "", type=str)
        except Exception:
            last = ""
        pool = [i for i in ids if i != last] or ids
        pick = random.choice(pool)
        try:
            QSettings().setValue("feed/lastRecommend", pick)
        except Exception:
            pass
        return pick

    def _fetch_episodes(self, sid):
        """拿一部剧的可播分集并缓存（失败重试 3 次，避开匿名限流）。

        同一部剧只拉一次：已在缓存里直接返回；另一个线程正在拉时返回已缓存的部分，
        调用方用 _wait_episodes() 等它写完。
        """
        with self._lock:
            if sid in self._episodes:
                return self._episodes[sid]
            if sid in self._fetching:
                return None
            self._fetching.add(sid)
        try:
            eps = []
            for _ in range(3):
                try:
                    data = _api(f"/v1/episodes/{sid}")
                    eps = [e for e in data.get("items", []) if e.get("playable")]
                    break
                except Exception:
                    time.sleep(2)
            return self._store_episodes(sid, eps[:EPISODES_PER_SERIES])
        finally:
            with self._lock:
                self._fetching.discard(sid)

    def _ensure_episodes(self, sid):
        """搜索结果 / 首次进入 / 预载的剧：分集列表可能还没拉过"""
        if sid not in self._episodes:
            if self._fetch_episodes(sid) is None:
                self._wait_episodes(sid)     # 另一个线程正在拉同一部，等它写完

    def _wait_episodes(self, sid, timeout=25.0):
        """等另一个线程把这部剧的分集拉完。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if sid in self._episodes:
                    return self._episodes[sid]
            time.sleep(0.1)
        return []

    def _store_episodes(self, sid, eps):
        with self._lock:
            self._episodes[sid] = [
                {
                    "id": e["id"],
                    "number": e.get("number") or (j + 1),
                    "label": e.get("title") or f"第{e.get('number', j + 1)}集",
                    "duration": int(e.get("duration_seconds") or 0),
                    "urls": {},          # _url_key(definition, strict) -> 播放地址（各清晰度地址不同，分别缓存）
                    "resolving": set(),  # 正在解析的 _url_key
                }
                for j, e in enumerate(eps)
            ]
            # 搜索结果回来的 episode_count 可能为 0，拿到真实分集后补上，否则选集/连播无法翻页
            for d in self._dramas:
                if d["id"] == sid and not d["total"] and eps:
                    d["total"] = len(eps)
                    self.dramasChanged.emit()
                    break
            return self._episodes[sid]

    # ---------- 搜索 ----------
    @Slot(str)
    def search(self, query):
        query = (query or "").strip()
        if not query:
            self.searchResults.emit("", [])
            return
        threading.Thread(target=self._search, args=(query,), daemon=True).start()

    def _search(self, query):
        try:
            data = _api("/v1/search?q=" + urllib.parse.quote(query), timeout=30, tries=2)
        except Exception as e:
            print(f"[sdk] search failed: {e}", flush=True)
            self.toast.emit(f"搜索失败：{e}")
            self.searchResults.emit(query, [])
            return

        items = []
        seen = set()                 # 接口偶尔返回重复 id，同一部剧只留一行
        known = {d["id"] for d in self._dramas}
        with self._lock:
            for s in data.get("items", []):
                sid = s.get("id")
                if not sid or not s.get("title") or sid in seen:
                    continue
                seen.add(sid)
                drama = {
                    "id": sid,
                    "title": s.get("title", ""),
                    "total": s.get("episode_count", 0),
                    "covers": list(COVER_PAIRS[len(items) % len(COVER_PAIRS)]),
                    "cover": "",              # 搜索结果不带封面地址，后台查 /v1/series 补
                    "cover_url": s.get("cover_url", ""),
                    "desc": s.get("description", ""),
                }
                items.append(drama)
                self._known.setdefault(sid, drama)
                # 并入剧单：MockData.drama(id) 才能解析到它，播放页直接可 open
                if sid not in known:
                    known.add(sid)
                    self._dramas.append(drama)
        print(f"[sdk] search {query!r}: {len(items)}", flush=True)
        if items:
            self.dramasChanged.emit()
        self.searchResults.emit(query, items)
        self._backfill_covers_async()

    # ---------- 封面 ----------
    @Slot(list)
    def rememberDramas(self, items):
        """启动时把观看历史 / 收藏夹里的剧并入剧单（只存了快照：id / 标题 / 集数 / 简介）。
        不在当前推荐流里的剧也解析得到，打开即可续播；封面已缓存的直接用，其余后台按 id 补。"""
        added = 0
        with self._lock:
            have = {d["id"] for d in self._dramas}
            for it in items or []:
                sid = str(it.get("id") or "")
                if not sid or sid in self._known:
                    continue
                cover = os.path.join(self._cover_dir, f"{sid}.jpg")
                drama = {
                    "id": sid,
                    "title": it.get("title") or "",
                    "total": int(it.get("total") or 0),
                    "covers": list(COVER_PAIRS[len(self._known) % len(COVER_PAIRS)]),
                    "cover": _file_url(cover) if os.path.exists(cover) else "",
                    "cover_url": "",
                    "desc": it.get("desc") or "",
                }
                self._known[sid] = drama
                if sid not in have:
                    self._dramas = self._dramas + [drama]
                    added += 1
        if added:
            self.dramasChanged.emit()
            self._backfill_covers_async()

    def _backfill_covers_async(self, limit=None):
        with self._lock:
            if self._covering:
                # 上一批还没跑完：记下来等它结束再补一轮。
                # 不能直接丢弃 —— 搜索刚回来时启动那批通常还在跑，丢了搜索结果就没图了。
                self._cover_again = True
                return
            self._covering = True
        threading.Thread(target=self._backfill_covers, args=(limit,), daemon=True).start()

    def _cover_urls_batch(self, ids):
        """用 /v1/series-batch 一次拿多部剧的封面地址，返回 {id: cover_url}。

        优先取「第一集的封面」：上游给的是 JPEG，能直接存下来用；
        而 series 自己的 cover_url 是 HEIC，还得 ffmpeg 解一遍。
        注意别把一次请求塞太多：后端逐部回源，11 部要 4 秒；拆成两批并发反而更慢
        （后端会互相拖慢），实测单批 6 部约 1.8 秒最稳。
        """
        out = {}
        if not ids:
            return out
        t0 = time.time()
        try:
            data = _api("/v1/series-batch?ids=" + ",".join(ids), timeout=30, tries=2, gap=0.8)
        except Exception as e:
            print(f"[sdk] series-batch 失败: {e}", flush=True)
            return out
        print(f"[sdk] series-batch {len(ids)} 部 {time.time() - t0:.2f}s", flush=True)
        for item in (data or []):
            if not isinstance(item, dict):
                continue
            s = item.get("series") or item
            sid = str(s.get("id") or "")
            if not sid:
                continue
            url = ""
            eps = item.get("episodes") or []
            if eps and isinstance(eps[0], dict):
                url = eps[0].get("cover_url") or ""
            if not url:
                url = s.get("cover_url") or ""
            if url:
                out[sid] = url
        return out

    def _backfill_covers(self, limit=None):
        """后台补真实封面，每拿到一张就发一次 dramasChanged，列表逐行出图。

        剧单项自带 cover_url；搜索结果没有，用 /v1/series-batch 批量取。
        转码是 CPU 密集操作，所以按 limit 控制单次数量（启动只补首屏那几张）。
        """
        try:
            self._backfill_covers_inner(limit)
        finally:
            with self._lock:
                self._covering = False
                again = self._cover_again
                self._cover_again = False
            if again:
                self._backfill_covers_async()     # 期间又有新剧要补（比如刚搜完）

    def _backfill_covers_inner(self, limit=None):
        with self._lock:
            feed = set(self._feed_ids)
            todo = [(d["id"], d.get("cover_url", "")) for d in self._dramas
                    if not d.get("cover") and not d.get("cover_tried")]
            # 用户正在看的（搜索结果 / 历史里的剧）优先出图，频道剧单的封面可以稍后
            todo.sort(key=lambda job: 1 if job[0] in feed else 0)
            if limit:
                todo = todo[:limit]
            taken = {did for did, _ in todo}
            for d in self._dramas:
                if d["id"] in taken:
                    d["cover_tried"] = True
        if not todo:
            return

        # 只有「没有 cover_url」的才需要查地址（搜索结果就是这种）。
        # 频道剧单自带的是 HEIC，但能直接转码，没必要为它多查一次 batch ——
        # 实测把 11 部塞进一次 batch 要 4 秒，只查搜索结果 6 部 1.5 秒左右。
        need_batch = [did for did, url in todo if not url]
        if need_batch:
            batch = self._cover_urls_batch(need_batch)
            todo = [(did, batch.get(did) or url) for did, url in todo]

        def one(job):
            did, url = job
            if not url:
                return (did, "", "no cover_url")
            cover = _cover_file(did, url, self._cover_dir)
            return (did, cover, "" if cover else "transcode failed")

        q = Queue()
        for job in todo:
            q.put(job)

        def worker():
            while True:
                try:
                    job = q.get_nowait()
                except Empty:
                    return
                res = one(job)
                if not res:
                    continue
                did, cover, err = res
                with self._lock:
                    for d in self._dramas:
                        if d["id"] == did:
                            if cover:
                                d["cover"] = cover
                            else:
                                d["cover_error"] = err    # 服务端拒绝时不重试，界面用占位渐变
                            break
                if cover:
                    self.dramasChanged.emit()
                    print(f"[sdk] cover ready {did}", flush=True)

        for _ in range(min(COVER_WORKERS, len(todo))):
            threading.Thread(target=worker, daemon=True).start()

    # ---------- 播放地址 ----------
    @Slot(str, int, str, bool, bool)
    def prepare(self, drama_id, episode, definition, strict, seekable):
        threading.Thread(target=self._prepare, args=(drama_id, episode, definition, strict, seekable),
                         daemon=True).start()

    def _prepare(self, drama_id, episode, definition, strict=False, seekable=False):
        """seekable：要从中途起播（续播 / 换清晰度）。没落盘的集是实时流、不能 seek，只能从头播，
        所以先等 SDK 落盘（3–8 秒）再给地址。换清晰度（strict）总是需要。"""
        need_cache = strict or seekable
        print(f"[sdk] prepare {drama_id} ep={episode} def={definition or QUALITY}"
              f"{' strict' if strict else ''}{' seekable' if need_cache else ''}", flush=True)
        self._current_drama = drama_id      # 切频道时记进 _channel_last，切回来直接回到这部
        # 调试用：HG_LOCAL_MP4 指向本地文件时跳过网络，直接播本地（验证渲染性能）
        import os
        local = os.environ.get("HG_LOCAL_MP4")
        if local:
            print(f"[sdk] 本地文件模式: {local}", flush=True)
            self.episodeReady.emit(drama_id, episode, local, definition)
            return
        self._ensure_episodes(drama_id)
        with self._lock:
            eps = self._episodes.get(drama_id)
            if not eps or not (0 <= episode < len(eps)):
                print(f"[sdk] no episode: have={len(eps) if eps else 0}", flush=True)
                self.episodeFailed.emit(drama_id, episode, "剧集不存在", definition)
                return
            ep = eps[episode]
            key = _url_key(definition, strict)
            url = ep["urls"].get(key)
            if url and not need_cache:
                self.episodeReady.emit(drama_id, episode, url, definition)
                return
            rkey = key + ("@seek" if need_cache else "")
            if rkey in ep["resolving"]:
                return                  # 同一请求正在解析，解析完会发 episodeReady
            ep["resolving"].add(rkey)
            eid = ep["id"]

        duration = 0
        try:
            cached = False              # 地址是之前解析的：是否已落盘不知道，交给 _wait_cached 查（已落盘时立即返回）
            if not url:
                # 本地 SDK 默认缓存优先：这一集落过盘就返回缓存的那一档，不管请求的是哪档；
                # strict=1 时只认请求的这一档，没缓存就向上游解析（换清晰度必须用它）
                info = _api(f"/v1/play/{eid}?definition={definition or QUALITY}"
                            f"{'&strict=1' if strict else ''}", timeout=45)
                url = info.get("stream_url")
                duration = int(info.get("duration_seconds") or 0)
                cached = bool(info.get("cached"))
            if need_cache and url and not cached:
                _wait_cached(eid, _url_definition(url, definition or QUALITY))
        except AnonLimited:
            # 上游对匿名设备关了数据通道：只有已经缓存的集还能播
            print("[sdk] 匿名额度用尽：无法解析新的播放地址", flush=True)
            with self._lock:
                ep["resolving"].discard(rkey)
            self.episodeFailed.emit(drama_id, episode,
                                    "上游暂时限制了匿名访问，换一部已缓存的剧或稍后再试", definition)
            return
        except Exception as e:
            print(f"[sdk] play failed: {e}", flush=True)
            with self._lock:
                ep["resolving"].discard(rkey)
            self.episodeFailed.emit(drama_id, episode, str(e), definition)
            return

        with self._lock:
            ep["resolving"].discard(rkey)
            if url:
                ep["urls"][key] = url
            if duration:
                ep["duration"] = duration
        if not url:
            self.episodeFailed.emit(drama_id, episode, "没有拿到播放地址", definition)
            return
        print(f"[sdk] url ok ep={episode} {url[:60]}", flush=True)
        self.episodeReady.emit(drama_id, episode, url, definition)

    # ---------- 弹幕 ----------
    # 本地 SDK 的 /v1/danmaku 一页是服务端划出的一段播放时间，可能没有弹幕但 has_more 仍为真，
    # 所以要一页页翻到 has_more 为假；整集一次拉完、按出现时间排好，播放时按位置直接取。
    @Slot(str, int)
    def danmaku(self, drama_id, episode):
        """要这一集（0 起的序号）的弹幕：内存 / 磁盘有就直接回，没有就后台翻页拉。

        弹幕不影响播放：失败只打日志，不弹 toast。
        """
        threading.Thread(target=self._danmaku_worker, args=(str(drama_id), int(episode)),
                         daemon=True).start()

    def _danmaku_worker(self, drama_id, episode):
        # 接口要的是这一集的 id（Episode.ID），和播放地址同源
        self._ensure_episodes(drama_id)
        with self._lock:
            eps = self._episodes.get(drama_id) or []
            if not (0 <= episode < len(eps)):
                return
            eid = str(eps[episode]["id"])
        key = (drama_id, eid)
        with self._lock:
            cached = self._danmaku.get(key)
            if cached is None and key not in self._danmaku_fetching:
                self._danmaku_fetching.add(key)
                owner = True
            else:
                owner = False
        if cached is not None:
            self.danmakuLoaded.emit(drama_id, episode)
            return
        if not owner:
            return                          # 另一个线程正在拉同一集，拉完会发信号
        try:
            items = self._read_danmaku_cache(drama_id, eid)
            if items is None:
                items = self._fetch_danmaku(drama_id, eid)
                self._write_danmaku_cache(drama_id, eid, items)
            with self._lock:
                self._danmaku[key] = items
        except AnonLimited:
            print("[sdk] 弹幕：匿名额度用尽，这一集跳过", flush=True)
            return
        except Exception as e:
            print(f"[sdk] 弹幕 {drama_id} ep={episode} 失败: {e}", flush=True)
            return
        finally:
            with self._lock:
                self._danmaku_fetching.discard(key)
        self.danmakuLoaded.emit(drama_id, episode)

    def _fetch_danmaku(self, drama_id, eid):
        path = f"/v1/danmaku/{urllib.parse.quote(drama_id)}/{urllib.parse.quote(eid)}"
        items = {}
        cursor = ""
        for _ in range(120):               # 一集最多 8093 条 / 每页 90 ≈ 90 页，留足余量
            q = path + ("?cursor=" + urllib.parse.quote(cursor, safe="") if cursor else "")
            page = _api(q, timeout=25, tries=2)
            for it in page.get("items") or []:
                text = str(it.get("text") or "").strip()
                offset = int(it.get("offset_ms") or 0)
                if not text or offset < 0:
                    continue
                items[it.get("id") or f"{offset}:{text}"] = {
                    "id": str(it.get("id") or ""),
                    "text": text,
                    "offset": offset,
                    "likes": int(it.get("likes") or 0),
                }
            cursor = page.get("cursor") or ""
            if not page.get("has_more") or not cursor:
                break
        return sorted(items.values(), key=lambda d: (d["offset"], d["id"]))

    def _danmaku_cache_path(self, drama_id, eid):
        safe = lambda s: "".join(c for c in str(s) if c.isalnum()) or "x"
        return os.path.join(self._danmaku_dir, f"{safe(drama_id)}_{safe(eid)}.json")

    def _read_danmaku_cache(self, drama_id, eid):
        """磁盘缓存：文件不存在返回 None（要联网拉），存在就返回列表（可能为空集）。"""
        try:
            with open(self._danmaku_cache_path(drama_id, eid), "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None
        out = []
        for it in data.get("items") or []:
            text = str(it.get("text") or "").strip()
            if not text:
                continue
            out.append({"id": str(it.get("id") or ""), "text": text,
                        "offset": int(it.get("offset") or 0),
                        "likes": int(it.get("likes") or 0)})
        return out

    def _write_danmaku_cache(self, drama_id, eid, items):
        path = self._danmaku_cache_path(drama_id, eid)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"episode": eid, "items": items}, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception as e:
            print(f"[sdk] 弹幕缓存写入失败: {e}", flush=True)

    @Slot(str, int, result="QVariantList")
    def danmakuFor(self, drama_id, episode):
        """已经拉到的这一集弹幕（按出现时间排序）；还没到 / 没有就返回空列表。"""
        drama_id = str(drama_id)
        with self._lock:
            eps = self._episodes.get(drama_id) or []
            if not (0 <= episode < len(eps)):
                return []
            items = self._danmaku.get((drama_id, str(eps[episode]["id"])))
        return items or []

    # ---------- 预取 / 预载 ----------
    @Slot(list, str)
    def preload(self, items, definition):
        """预载往后要看的几个节目（播放页给出顺序：越近越前，见 8.3 节）。

        逐个落盘而不是同时开跑：几个一起下会互相抢带宽，最近的那个反而最晚好。
        每次调用替换还没开始的排队项（用户换了位置，旧的顺序就不对了）；正在落盘的那个跑完为止。
        items: [[dramaId, ep], ...]
        """
        queue = []
        with self._lock:
            for it in items or []:
                key = (str(it[0]), int(it[1]), definition)
                if key not in self._prefetched and key not in queue:
                    queue.append(key)
            self._preload_queue = queue
            if not queue or self._preloading:
                return
            self._preloading = True
        threading.Thread(target=self._preload_worker, name="preload", daemon=True).start()

    def _preload_worker(self):
        while True:
            with self._lock:
                key = None
                while self._preload_queue:
                    k = self._preload_queue.pop(0)
                    if k not in self._prefetched:
                        key = k
                        break
                if key is None:
                    self._preloading = False
                    return
                self._prefetched.add(key)
            if not self._prefetch(*key):
                with self._lock:              # 上游拒绝：后面的也不会成功，别再打
                    self._preload_queue = []
                    self._preloading = False
                return

    @Slot(str, int, str)
    def prefetch(self, drama_id, episode, definition):
        """提前准备某一集（解析地址 + 让服务端落盘），本集临近结尾时由播放页调用。"""
        key = (drama_id, episode, definition)
        with self._lock:
            eps = self._episodes.get(drama_id) or []
            if not (0 <= episode < len(eps)):
                return                     # 没有这一集（本剧最后一集）
            if key in self._prefetched:
                return                     # 已经在解析 / 已解析好
            self._prefetched.add(key)
        # 等落盘也在这个线程里：落了盘才能抽首帧，信息流里自动连播的下一集也要靠它无缝接上
        threading.Thread(target=self._prefetch, args=(drama_id, episode, definition),
                         daemon=True).start()

    def _prefetch(self, drama_id, episode, definition):
        """提前准备某一集：解析播放地址 + 让服务端落盘（prewarm）+ 抽首帧。返回 False 表示上游拒绝。

        等落盘真正完成再返回。SDK 的 prewarm 是立即返回 202、后台落盘的，
        预载不等的话几集会同时下载，和正在看的那一集抢带宽（它要落盘了才能 seek）。

        落盘后切集时 ohgd 直接读本地 mp4，秒开（也能 seek）；不落盘就要等实时转封装。
        服务端落盘 3–8 秒、约 6MB，所以必须提前（见 8.3 节）。
        """
        key = (drama_id, episode, definition)
        q = definition or QUALITY
        try:
            self._ensure_episodes(drama_id)   # 预载的可能是还没打开过的剧
            with self._lock:
                eps = self._episodes.get(drama_id) or []
                if not (0 <= episode < len(eps)):
                    return True
                ep = eps[episode]
            eid = ep["id"]

            # 1) 先解析地址（缓存里还没有时），拿到就能播
            if not ep["urls"].get(_url_key(definition, False)):
                info = _api(f"/v1/play/{eid}?definition={q}", timeout=45)
                with self._lock:
                    if info.get("stream_url"):
                        ep["urls"][_url_key(definition, False)] = info["stream_url"]
                    d = int(info.get("duration_seconds") or 0)
                    if d:
                        ep["duration"] = d

            # 2) 让服务端落盘：已落盘时立即返回 ready，重复调用很便宜
            _api(f"/v1/cache/prewarm/{eid}?definition={q}", timeout=180, tries=1)
            _wait_cached(eid, q, timeout=90)
            # 3) 抽首帧：切到这一集时先显示它，起播后画面从同一帧接上
            if _make_poster(eid, q, self._video_dir, self._cover_dir):
                self._bump_posters()
            print(f"[sdk] 预取就绪 {drama_id} ep={episode}", flush=True)
            return True
        except AnonLimited:
            print("[sdk] 上游拒绝（额度/签名），跳过预取", flush=True)
            return False
        except Exception as e:
            # 失败清除标记，下次预载 / 临近结尾时会再试
            with self._lock:
                self._prefetched.discard(key)
            print(f"[sdk] 预取未完成 {drama_id} ep={episode}: {e}", flush=True)
            return True

    @Slot(str, int, result=int)
    def durationOf(self, drama_id, episode):
        with self._lock:
            eps = self._episodes.get(drama_id) or []
            if 0 <= episode < len(eps):
                return eps[episode]["duration"]
        return 0

    # ---------- 首帧图 ----------
    def _bump_posters(self):
        with self._lock:
            self._poster_rev += 1
        self.postersChanged.emit()

    @Property(int, notify=postersChanged)
    def posterRevision(self):
        return self._poster_rev

    @Slot(str, int, result=str)
    def posterOf(self, drama_id, episode):
        """这一集第一帧的本地图片地址；还没预取落盘（或抽帧失败）时返回 ""，界面退回剧封面。
        QML 绑定里同时读 posterRevision，有新图时会重新求值。"""
        with self._lock:
            eps = self._episodes.get(drama_id) or []
            if not (0 <= episode < len(eps)):
                return ""
            eid = eps[episode]["id"]
        path = _poster_path(eid, self._cover_dir)
        return _file_url(path) if os.path.exists(path) else ""

    @Slot(str, int, result=str)
    def episodeLabel(self, drama_id, episode):
        with self._lock:
            eps = self._episodes.get(drama_id) or []
            if 0 <= episode < len(eps):
                return eps[episode]["label"]
        return f"第{episode + 1}集"