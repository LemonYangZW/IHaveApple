"""Windows 原生窗口辅助：9:16 等比缩放；全局快捷键（一键隐藏）。

原型最初在 QML 里跟随鼠标逐个设置 x / y / width / height。每次鼠标移动都会触发多次窗口几何变化
和交换链重建，拖动边缘时明显掉帧、画面跟不上鼠标。

现在改为由系统接管缩放（QML 调用 startSystemResize），在 WM_SIZING 中直接修正拖拽矩形。
窗口尺寸在一次 SetWindowPos 内确定，和普通窗口缩放一样跟手。C++ 正式版使用同样的做法。
"""
import ctypes
import re
import sys
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal, Slot

WM_SIZING = 0x0214
WMSZ_LEFT, WMSZ_RIGHT, WMSZ_TOP, WMSZ_TOPLEFT, WMSZ_TOPRIGHT, WMSZ_BOTTOM, WMSZ_BOTTOMLEFT, WMSZ_BOTTOMRIGHT = range(1, 9)
_LEFT_SIDE = (WMSZ_LEFT, WMSZ_TOPLEFT, WMSZ_BOTTOMLEFT)
_TOP_SIDE = (WMSZ_TOP, WMSZ_TOPLEFT, WMSZ_TOPRIGHT)


def fit_aspect(edge, rect, aspect, min_height, max_height):
    """按拖动的边修正矩形 (left, top, right, bottom)，返回保持 aspect（宽 / 高）的新矩形。

    拖左右边：宽度决定高度；拖上下边：高度决定宽度；拖角：取面积较大的一种，手感不会"卡住"。
    被拖动的边跟随鼠标，对边保持不动。
    """
    left, top, right, bottom = rect
    w, h = right - left, bottom - top
    if edge in (WMSZ_LEFT, WMSZ_RIGHT):
        h = w / aspect
    elif edge in (WMSZ_TOP, WMSZ_BOTTOM):
        w = h * aspect
    elif w / h > aspect:
        h = w / aspect
    h = round(max(min_height, min(h, max_height)))
    w = round(h * aspect)
    if edge in _LEFT_SIDE:
        left = right - w
    else:
        right = left + w
    if edge in _TOP_SIDE:
        top = bottom - h
    else:
        bottom = top + h
    return left, top, right, bottom


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def _work_area_height(hwnd):
    user32 = ctypes.windll.user32
    user32.MonitorFromWindow.restype = ctypes.c_void_p
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
    info = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST：窗口所在的显示器
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return 1 << 30
    return info.rcWork.bottom - info.rcWork.top


# Qt 的窗口过程不会把 WM_SIZING 交给 QAbstractNativeEventFilter，所以直接子类化窗口过程。
_LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_GWLP_WNDPROC = -4


class AspectResizeHook(QObject):
    """子类化窗口过程：拦截 WM_SIZING 保持宽高比，其余消息交回 Qt。
    最小高度按逻辑像素给出；最大高度为窗口所在显示器的工作区高度。

    继承 QObject 是为了让 QML 能直接调用 set_aspect()（「窗口适配视频比例」开关）。"""

    def __init__(self, window, aspect, min_height, parent=None):
        super().__init__(parent)
        self.window = window
        self.aspect = aspect
        self.min_height = min_height
        user32 = ctypes.windll.user32
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        user32.CallWindowProcW.restype = _LRESULT
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self._user32 = user32
        self._proc = _WNDPROC(self._wndproc)        # 持有引用，防止回调被回收
        self._original = user32.SetWindowLongPtrW(int(window.winId()), _GWLP_WNDPROC,
                                                  ctypes.cast(self._proc, ctypes.c_void_p))

    @Slot(float)
    def set_aspect(self, aspect):
        """换锁定比例（宽 / 高）。「窗口适配视频」开关会改这个值。"""
        if aspect and aspect > 0:
            self.aspect = float(aspect)

    @Slot(int)
    def set_min_height(self, min_height):
        if min_height and min_height > 0:
            self.min_height = int(min_height)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_SIZING:
            try:
                rc = wintypes.RECT.from_address(lparam)
                dpr = self.window.devicePixelRatio()
                rc.left, rc.top, rc.right, rc.bottom = fit_aspect(
                    wparam, (rc.left, rc.top, rc.right, rc.bottom), self.aspect,
                    round(self.min_height * dpr), _work_area_height(hwnd))
                return 1
            except Exception as e:  # 回调里的异常不能抛回系统
                print("[native_window]", e, file=sys.stderr)
        return self._user32.CallWindowProcW(self._original, hwnd, msg, wparam, lparam)


def install_aspect_resize(window, aspect, min_height):
    """在 Windows 上为窗口安装等比缩放，返回钩子对象（调用方需持有引用）；其他平台返回 None。"""
    if sys.platform != "win32":
        return None
    return AspectResizeHook(window, aspect, min_height)


# ---------- 全局快捷键 ----------
# 一键隐藏要在窗口、任务栏、托盘图标都没了之后还能按回来，程序内的 QML Shortcut 收不到（没有焦点），
# 所以用 RegisterHotKey 注册系统级热键。消息发给一个只收消息的隐藏窗口（HWND_MESSAGE），
# 不用再子类化主窗口 —— 主窗口的每条消息就不必多绕一趟 Python。
WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
_HWND_MESSAGE = -3
_HOTKEY_ID = 1
# 与 Store.sequenceFromEvent 生成的按键名对应
_NAMED_VK = {"Space": 0x20, "PgUp": 0x21, "PgDown": 0x22, "End": 0x23, "Home": 0x24,
             "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28, "Ins": 0x2D, "Del": 0x2E,
             "Return": 0x0D, "Tab": 0x09}


def parse_sequence(seq, vk_scan=None):
    """把「Ctrl+Alt+H」「F9」「`」这类按键序列转成 RegisterHotKey 的 (modifiers, vk)；认不出返回 None。
    vk_scan：字符 → VkKeyScanW 结果（符号键用；默认调系统，测试时可注入）。"""
    parts = re.split(r"\+(?!$)", seq or "")
    if not parts or not parts[-1]:
        return None
    mods = MOD_NOREPEAT                      # 按住不放不重复触发，免得窗口闪来闪去
    for m in parts[:-1]:
        flag = {"Ctrl": MOD_CONTROL, "Alt": MOD_ALT, "Shift": MOD_SHIFT}.get(m)
        if flag is None:
            return None
        mods |= flag
    key = parts[-1]
    if key in _NAMED_VK:
        return mods, _NAMED_VK[key]
    if re.fullmatch(r"F([1-9]|1[0-9]|2[0-4])", key):
        return mods, 0x70 + int(key[1:]) - 1
    if len(key) != 1:
        return None
    if key.isascii() and key.isalnum():
        return mods, ord(key.upper())
    # 符号键：按当前键盘布局查虚拟键码；需要 Shift 才能打出的符号（如 {）补上 Shift
    if vk_scan is None:
        vk_scan = ctypes.windll.user32.VkKeyScanW
        vk_scan.restype = ctypes.c_short                     # 返回 SHORT：-1 表示当前布局打不出这个字符
        vk_scan.argtypes = [wintypes.WCHAR]
    r = vk_scan(key)
    if r == -1 or (r & 0xFF) == 0xFF:
        return None
    if (r >> 8) & 1:
        mods |= MOD_SHIFT
    return mods, r & 0xFF


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class GlobalHotkey(QObject):
    """系统级快捷键：在任何程序里按下都会发 activated()。QML 调 setSequence() 改键，返回是否注册成功
    （被别的程序占用时失败）；传空字符串取消。"""
    activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        u = ctypes.WinDLL("user32", use_last_error=True)   # 独立实例：不改共享 windll.user32 的 argtypes
        u.DefWindowProcW.restype = _LRESULT
        u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u.CreateWindowExW.restype = wintypes.HWND
        u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        u.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        u.DestroyWindow.argtypes = [wintypes.HWND]
        self._u = u
        self._registered = False
        self._proc = _WNDPROC(self._wndproc)                # 持有引用，防止回调被回收
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetModuleHandleW.restype = wintypes.HMODULE      # 句柄要声明类型，默认 int 在 64 位下会被截断
        k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        u.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
        u.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        hinst = k32.GetModuleHandleW(None)
        # 每个实例一个窗口类：类名相同时 RegisterClassW 会失败，新窗口就用了上一个实例的窗口过程，信号发错对象
        self._hinst = hinst
        self._cls_name = f"IHaveAppleHotkey{id(self):x}"
        cls = _WNDCLASSW(lpfnWndProc=self._proc, hInstance=hinst, lpszClassName=self._cls_name)
        u.RegisterClassW(ctypes.byref(cls))
        self._hwnd = u.CreateWindowExW(0, self._cls_name, "", 0, 0, 0, 0, 0,
                                       _HWND_MESSAGE, None, hinst, None)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_HOTKEY and wparam == _HOTKEY_ID:
            try:
                self.activated.emit()
            except Exception as e:  # 回调里的异常不能抛回系统
                print("[hotkey]", e, file=sys.stderr)
            return 0
        return self._u.DefWindowProcW(hwnd, msg, wparam, lparam)

    @Slot(str, result=bool)
    def setSequence(self, seq):
        if self._registered:
            self._u.UnregisterHotKey(self._hwnd, _HOTKEY_ID)
            self._registered = False
        if not seq:
            return True
        parsed = parse_sequence(seq)
        if not parsed or not self._hwnd:
            print(f"[hotkey] 无法识别的按键：{seq}", file=sys.stderr, flush=True)
            return False
        self._registered = bool(self._u.RegisterHotKey(self._hwnd, _HOTKEY_ID, *parsed))
        if not self._registered:
            print(f"[hotkey] 注册失败（可能被其他程序占用）：{seq}", file=sys.stderr, flush=True)
        return self._registered

    def shutdown(self):
        self.setSequence("")
        if self._hwnd:
            self._u.DestroyWindow(self._hwnd)
            self._u.UnregisterClassW(self._cls_name, self._hinst)
            self._hwnd = None


def create_global_hotkey():
    """Windows 上返回 GlobalHotkey（调用方需持有引用）；其他平台返回 None。"""
    return GlobalHotkey() if sys.platform == "win32" else None
