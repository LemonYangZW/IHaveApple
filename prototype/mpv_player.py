"""mpv_player — libmpv 播放内核（SW 渲染 → QImage → QML 纹理）

为什么用 SW 渲染而不是 OpenGL render API：
  QML 的渲染在 QSG 线程，libmpv 的 GL render API 需要绑定同一个 GL 上下文，
  在 Python/ctypes 下与该线程协作不稳定。SW 渲染拿到 RGB 帧后转成 QImage，
  由 VideoItem（纹理节点）绘制，简单可靠且不依赖 QtMultimedia。

线程：渲染在独立的渲染线程里进行，绝不放在 GUI 线程。
  mpv_render_context_render 默认（BLOCK_FOR_TARGET_TIME=1）会阻塞到这一帧的显示时刻才返回，
  曾经放在 GUI 线程的定时器里，播放时 GUI 线程约 100% 时间都卡在这里：
  拖动窗口的系统移动循环和 Qt Quick 的同步都抢不到时间 → 拖动卡顿、帧节奏忽快忽慢。
  现在渲染线程由 mpv 的更新回调唤醒，阻塞正好用来卡准每帧的显示时刻；GUI 线程只负责 update()。
  渲染线程里不调用 mpv_get_property 等需要等待播放核心的接口（核心可能反过来等渲染线程 → 死锁），
  视频尺寸由 GUI 线程轮询后缓存。
"""

import ctypes as C
import os
import threading

from PySide6.QtCore import QObject, QTimer, Signal, Property, Slot
from PySide6.QtGui import QImage

HERE = os.path.dirname(os.path.abspath(__file__))
DLL = os.path.join(HERE, "lib", "libmpv-2.dll")

_lib = C.CDLL(DLL)
_lib.mpv_create.restype = C.c_void_p
_lib.mpv_initialize.argtypes = [C.c_void_p]
_lib.mpv_initialize.restype = C.c_int
_lib.mpv_set_option_string.argtypes = [C.c_void_p, C.c_char_p, C.c_char_p]
_lib.mpv_set_option_string.restype = C.c_int
_lib.mpv_command_string.argtypes = [C.c_void_p, C.c_char_p]
_lib.mpv_command_string.restype = C.c_int
_lib.mpv_get_property.argtypes = [C.c_void_p, C.c_char_p, C.c_int, C.c_void_p]
_lib.mpv_get_property.restype = C.c_int
_lib.mpv_terminate_destroy.argtypes = [C.c_void_p]
_lib.mpv_render_context_create.argtypes = [C.POINTER(C.c_void_p), C.c_void_p, C.c_void_p]
_lib.mpv_render_context_create.restype = C.c_int
_lib.mpv_render_context_set_update_callback.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p]
_lib.mpv_render_context_update.argtypes = [C.c_void_p]
_lib.mpv_render_context_update.restype = C.c_uint64
_lib.mpv_render_context_render.argtypes = [C.c_void_p, C.c_void_p]
_lib.mpv_render_context_render.restype = C.c_int
_lib.mpv_render_context_report_swap.argtypes = [C.c_void_p]
_lib.mpv_render_context_free.argtypes = [C.c_void_p]

FMT_DOUBLE = 5
P_API_TYPE, P_SW_SIZE, P_SW_FORMAT, P_SW_STRIDE, P_SW_POINTER, P_END = 1, 17, 18, 19, 20, 0


class _RParam(C.Structure):
    _fields_ = [("type", C.c_int), ("data", C.c_void_p)]


UPDATE_CB = C.CFUNCTYPE(None, C.c_void_p)


class MpvPlayer(QObject):
    """单实例播放器：一次只播一条，切集用 loadfile replace"""

    ready = Signal()                 # 首帧就绪
    frameReady = Signal()            # 有新帧可绘制
    positionChanged = Signal()
    durationChanged = Signal()
    stateChanged = Signal()
    videoSizeChanged = Signal()      # 源视频尺寸变化（载入新片 / 首帧到达）
    ended = Signal()                 # 播到文件末尾（keep-open=no：播完即回到 idle）
    errorOccurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = None               # 最新一帧（深拷贝，交给 VideoItem 绘制）
        self._handle = None
        self._rc = C.c_void_p()
        self._buf = None
        self._size = (C.c_int * 2)(0, 0)
        self._fmt = C.c_char_p(b"bgra")   # 不用 bgr0：填充字节为 0，纹理 alpha=0，截图里画面是透明的
        self._stride = C.c_size_t(0)
        self._ptr = C.c_void_p(0)
        self._wh = (0, 0)
        self._target_wh = (0, 0)     # 控件尺寸（VideoItem 上报），0 = 未上报
        self._video_wh = (0, 0)      # 源视频尺寸，GUI 线程轮询后缓存给渲染线程
        # 装载代数：每次 loadfile +1。渲染线程在一帧渲染前后各看一次，变了就丢掉这一帧 ——
        # 否则装载前就开始渲染的旧片那一帧会被当成新片首帧（ready 提前触发，切集时闪一下上一集的画面）
        self._gen = 0
        self._wake = threading.Event()   # mpv 更新回调 → 唤醒渲染线程
        self._running = True
        self._cb = None
        self._first_frame = False
        self._eof_sent = True        # 本片的「播完」已通知过 / 不该通知（装载新片时重置）
        self._last_pos = -1.0
        self._init_mpv()

        self._render_thread = threading.Thread(target=self._render_loop, name="mpv-render", daemon=True)
        self._render_thread.start()

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_state)
        self._poll.start(100)

    # ---------- 初始化 ----------
    def _init_mpv(self):
        self._handle = _lib.mpv_create()
        for k, v in {
            "vo": "libmpv",
            "hwdec": "no",               # SW 渲染路径拿不到显存帧，硬解不可用
            "osc": "no",
            "osd-level": "0",
            "input-default-bindings": "no",
            "input-vo-keyboard": "no",
            "keep-open": "no",
            "idle": "yes",
            "really-quiet": "yes",
            "cache": "yes",
            "cache-secs": "20",
            "demuxer-readahead-secs": "20",
            "video-sync": "audio",
            "audio-client-name": "IHaveApple",
        }.items():
            _lib.mpv_set_option_string(self._handle, k.encode(), v.encode())
        if _lib.mpv_initialize(self._handle) < 0:
            raise RuntimeError("mpv_initialize failed")

        api = C.c_char_p(b"sw")
        # 必须是结构体数组，不能是指针数组
        params = (_RParam * 2)(
            _RParam(P_API_TYPE, C.cast(api, C.c_void_p)),
            _RParam(P_END, None),
        )
        rc = _lib.mpv_render_context_create(C.byref(self._rc), self._handle,
                                            C.cast(params, C.c_void_p))
        if rc < 0:
            raise RuntimeError(f"sw render context failed: {rc}")

        # 回调在 mpv 内部线程触发，按 render.h 只能做通知，不能调用任何 mpv 接口
        self._cb = UPDATE_CB(lambda _: self._wake.set())
        _lib.mpv_render_context_set_update_callback(
            self._rc, C.cast(self._cb, C.c_void_p), None)

    # ---------- 渲染 ----------
    def _alloc(self, w, h):
        self._buf = (C.c_char * (w * h * 4))()
        self._size[0], self._size[1] = w, h
        self._stride = C.c_size_t(w * 4)
        self._ptr = C.cast(self._buf, C.c_void_p)
        self._wh = (w, h)

    def _render_loop(self):
        """渲染线程：等 mpv 通知 → 渲染（阻塞到显示时刻）→ 通知 GUI 线程刷新"""
        while self._running:
            # 超时兜底：视频尺寸尚未轮询到时，隔一会儿再试
            self._wake.wait(0.05)
            self._wake.clear()
            if self._running:
                self._render_frame()

    def _render_frame(self):
        gen = self._gen
        flags = _lib.mpv_render_context_update(self._rc)
        if not (flags & 1):     # MPV_RENDER_UPDATE_FRAME
            return

        w, h = self._video_wh
        if w <= 0 or h <= 0:
            return              # 帧已就绪但尺寸未知：等超时后再试（帧标志会保留）
        # 输出尺寸贴合控件：省掉「渲染大图再缩小」的双重开销
        tw, th = self._target_wh
        if tw >= 64 and th >= 64:
            scale = min(tw / w, th / h, 1.0)      # 不放大，避免无谓插值
        else:
            scale = min(1.0, 1920 / max(h, 1))    # 未知控件尺寸时的兜底
        # 限制上限（1080p），避免 4K 源拖垮 CPU；不能压得更低，否则大窗口会被 Qt 二次放大而变糊
        scale = min(scale, 1920 / max(h, 1))
        w, h = max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2)
        if (w, h) != self._wh or self._buf is None:
            self._alloc(w, h)

        # 类型严格按 render.h：
        #   SW_SIZE    int[2]*   -> 数组地址
        #   SW_FORMAT  char*     -> 字符串指针本身（不是 char**）
        #   SW_STRIDE  size_t*   -> 指针的地址
        #   SW_POINTER void*     -> 目标缓冲区地址本身
        params = (_RParam * 5)(
            _RParam(P_SW_SIZE, C.cast(self._size, C.c_void_p)),
            _RParam(P_SW_FORMAT, C.cast(self._fmt, C.c_void_p)),
            _RParam(P_SW_STRIDE, C.cast(C.byref(self._stride), C.c_void_p)),
            _RParam(P_SW_POINTER, C.cast(self._buf, C.c_void_p)),
            _RParam(P_END, None),
        )
        if _lib.mpv_render_context_render(self._rc, C.cast(params, C.c_void_p)) < 0:
            return
        _lib.mpv_render_context_report_swap(self._rc)
        if gen != self._gen:
            return              # 渲染期间装载了新片：这一帧属于上一片，丢掉

        # 深拷贝：mpv 会复用这块缓冲区，不能把指针交出去
        self._image = QImage(self._buf, w, h, w * 4, QImage.Format_RGB32).copy()
        self.frameReady.emit()

        if not self._first_frame:
            self._first_frame = True
            self.ready.emit()

    # ---------- 属性 ----------
    @property
    def image(self):
        return self._image

    @Property(float, notify=positionChanged)
    def position(self):
        return self._get_float("time-pos") or 0.0

    @Property(float, notify=durationChanged)
    def duration(self):
        return self._get_float("duration") or 0.0

    # 能否任意 seek：本地 SDK 没落盘时推的是边转边下的实时流，只能顺着播，
    # 这时 duration 也只是已下载的长度（会一直涨）。随轮询通知，绑定会跟着刷新
    @Property(bool, notify=durationChanged)
    def seekable(self):
        return bool(self._get_flag("seekable"))

    @Property(bool, notify=stateChanged)
    def paused(self):
        return bool(self._get_flag("pause"))      # pause / idle-active 是 flag，按 INT64 读会失败

    @Property(str, notify=stateChanged)
    def phase(self):
        if self._get_flag("idle-active"):
            return "loading" if self._first_frame else "ended"
        if self.paused:
            return "paused"
        return "playing"

    # 源视频分辨率（宽高各为 0 表示还没拿到）。窗口「适配视频比例」用这两个值。
    @Property(int, notify=videoSizeChanged)
    def videoWidth(self):
        return self._video_wh[0]

    @Property(int, notify=videoSizeChanged)
    def videoHeight(self):
        return self._video_wh[1]

    def _get_float(self, name):
        buf = C.c_double()
        r = _lib.mpv_get_property(self._handle, name.encode(), FMT_DOUBLE, C.byref(buf))
        return buf.value if r >= 0 else None

    def _get_flag(self, name):
        buf = C.c_int()
        r = _lib.mpv_get_property(self._handle, name.encode(), 3, C.byref(buf))  # MPV_FORMAT_FLAG
        return bool(buf.value) if r >= 0 else None

    def _get_int(self, name):
        buf = C.c_int64()        # MPV_FORMAT_INT64 写入 8 字节，用 c_int 会越界写
        r = _lib.mpv_get_property(self._handle, name.encode(), 4, C.byref(buf))  # MPV_FORMAT_INT64
        return buf.value if r >= 0 else None

    def _poll_state(self):
        wh = (self._get_int("width") or 0, self._get_int("height") or 0)
        if wh != self._video_wh:
            self._video_wh = wh
            self.videoSizeChanged.emit()     # 「窗口适配视频比例」据此重算窗口
        p = self._get_float("time-pos")
        if p != self._last_pos:
            self._last_pos = p
            self.positionChanged.emit()
            self.durationChanged.emit()
        # 播完：出过画面后回到 idle（stop() 主动停下的不算）
        if not self._eof_sent and self._first_frame and self._get_flag("idle-active"):
            self._eof_sent = True
            self.ended.emit()

    # ---------- 控制 ----------
    def _cmd(self, line):
        if self._handle:
            _lib.mpv_command_string(self._handle, line.encode())

    @Slot(int, int)
    def set_target_size(self, w, h):
        """控件尺寸变化时调用；下次渲染即按新尺寸输出"""
        if w > 0 and h > 0:
            self._target_wh = (int(w), int(h))

    def _load(self, target, start=0.0):
        self._gen += 1
        self._first_frame = False
        self._eof_sent = False
        self._video_wh = (0, 0)      # 新片尺寸可能不同：等轮询拿到再渲染，避免首帧比例错误
        # start 是全局选项，对之后每次 loadfile 都生效，所以每次装载都显式设一遍
        self._cmd(f"set start {max(0.0, float(start)):.3f}")
        self._cmd(f'loadfile "{target}" replace')

    @Slot(str)
    def load_url(self, url):
        self._load(url)

    @Slot(str, float)
    def load_url_at(self, url, sec):
        """从 sec 秒处起播（换清晰度时接着原位置播）"""
        self._load(url, sec)

    @Slot(str)
    def load_file(self, path):
        # mpv 的命令行解析里 "\\" 是转义符，Windows 路径必须改用正斜杠
        self._load(path.replace("\\", "/"))

    @Slot()
    def play(self):
        self._cmd("set pause no")

    @Slot()
    def pause(self):
        self._cmd("set pause yes")

    @Slot()
    def togglePause(self):
        self._cmd("cycle pause")

    @Slot(float)
    def seek(self, sec):
        self._cmd(f"seek {sec} absolute+exact")   # 精确到帧，不吸附到关键帧

    @Slot(float)
    def setSpeed(self, s):
        self._cmd(f"set speed {s}")

    @Slot(float)
    def setVolume(self, v):
        self._cmd(f"set volume {int(v * 100)}")

    @Slot(bool)
    def setMute(self, m):
        self._cmd(f"set mute {'yes' if m else 'no'}")

    @Slot()
    def stop(self):
        self._eof_sent = True
        self._cmd("stop")

    def shutdown(self):
        self._poll.stop()
        # 先停渲染线程再释放渲染上下文：渲染中的那一帧最多阻塞一个帧间隔
        self._running = False
        self._wake.set()
        self._render_thread.join(2.0)
        try:
            if self._rc:
                _lib.mpv_render_context_free(self._rc)
                self._rc = C.c_void_p()
        except Exception:
            pass
        try:
            if self._handle:
                _lib.mpv_terminate_destroy(self._handle)
                self._handle = None
        except Exception:
            pass
