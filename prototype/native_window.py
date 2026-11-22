"""Windows 原生窗口辅助：9:16 等比缩放。

原型最初在 QML 里跟随鼠标逐个设置 x / y / width / height。每次鼠标移动都会触发多次窗口几何变化
和交换链重建，拖动边缘时明显掉帧、画面跟不上鼠标。

现在改为由系统接管缩放（QML 调用 startSystemResize），在 WM_SIZING 中直接修正拖拽矩形。
窗口尺寸在一次 SetWindowPos 内确定，和普通窗口缩放一样跟手。C++ 正式版使用同样的做法。
"""
import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QObject, Slot

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
