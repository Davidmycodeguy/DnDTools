"""The hover value card on screen: an always-on-top window beside the game's item tooltip.

A native per-pixel-alpha layered window (UpdateLayeredWindow), so the card's rounded corners and
soft shadow blend with the game. It is click-through and only ever shown with SW_SHOWNOACTIVATE,
so the game keeps focus and every input. Its own thread runs the window's message loop and draws;
show/hide only store the request and post a message.
"""
import ctypes
import logging
import threading
import time
from ctypes import wintypes

from src.models.hover_card import render_card
from src.models.screen_grab import gdi, top_down_32bpp

logger = logging.getLogger(__name__)

GAP_PX = 12
WM_APP_SHOW, WM_APP_HIDE, WM_APP_CLOSE = 0x8001, 0x8002, 0x8003
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
AC_SRC_OVER, AC_SRC_ALPHA, ULW_ALPHA = 0x00, 0x01, 0x02


def use_physical_pixels():
    """Make this thread see real screen pixels. With display scaling (e.g. 150% on 4K), a
    DPI-unaware thread gets scaled cursor positions and screen sizes that don't match captures."""
    try:
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
    except (AttributeError, OSError):  # older Windows: the whole process is usually aware already
        pass


def place_panel(size, tooltip, screen):
    """(x, y) for a panel of `size` beside `tooltip` (left, top, right, bottom): left if it fits."""
    width, height = size
    left, top, right, _ = tooltip
    screen_w, screen_h = screen
    x = left - GAP_PX - width
    if x < 0:
        x = right + GAP_PX
    x = min(max(0, x), max(0, screen_w - width))
    y = min(max(0, top), max(0, screen_h - height))
    return x, y


def premultiplied_bgra(image):
    """Raw BGRA bytes with colour premultiplied by alpha, as UpdateLayeredWindow expects.
    PIL's own premultiplied mode ("RGBa") does it ~4x faster than numpy."""
    return image.convert("RGBA").convert("RGBa").tobytes("raw", "BGRa")


class _BlendFunction(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


def _gdi():  # pragma: no cover - Windows only
    """screen_grab's handle-safe user32/gdi32, plus UpdateLayeredWindow."""
    user32, gdi32 = gdi()
    user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                           ctypes.POINTER(wintypes.SIZE), wintypes.HDC,
                                           ctypes.POINTER(wintypes.POINT), wintypes.COLORREF,
                                           ctypes.POINTER(_BlendFunction), wintypes.DWORD]
    return user32, gdi32


def _blit(hwnd, image, x, y):  # pragma: no cover - Windows only
    """Put `image` (RGBA) on the layered window at screen (x, y) with per-pixel alpha."""
    user32, gdi32 = _gdi()
    width, height = image.size
    screen_dc = user32.GetDC(None)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(memory_dc, ctypes.byref(top_down_32bpp(width, height)), 0, ctypes.byref(bits),
                                    None, 0)
    try:
        data = premultiplied_bgra(image)
        ctypes.memmove(bits, data, len(data))
        old = gdi32.SelectObject(memory_dc, bitmap)
        blend = _BlendFunction(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(hwnd, screen_dc, ctypes.byref(wintypes.POINT(x, y)),
                                   ctypes.byref(wintypes.SIZE(width, height)), memory_dc,
                                   ctypes.byref(wintypes.POINT(0, 0)), 0, ctypes.byref(blend), ULW_ALPHA)
        gdi32.SelectObject(memory_dc, old)
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)


class HoverPanel:
    def __init__(self, render=render_card):
        self._render = render
        self._lock = threading.Lock()
        self._request = None     # (card, tooltip, screen) waiting to be shown
        self._hwnd = None
        self._ready = threading.Event()
        self._thread = None

    def _ensure_started(self):
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._ready.clear()
                self._thread = threading.Thread(target=self._main, daemon=True, name="HoverPanel")
                self._thread.start()
        self._ready.wait(timeout=2.0)

    def _post(self, message):
        if self._hwnd:
            import win32gui
            try:
                win32gui.PostMessage(self._hwnd, message, 0, 0)
            except Exception:
                logger.debug("Hover panel message failed", exc_info=True)

    def show(self, card, tooltip, screen):
        self._ensure_started()
        with self._lock:
            self._request = (card, tuple(tooltip), tuple(screen), time.perf_counter())
        self._post(WM_APP_SHOW)

    def hide(self):
        self._post(WM_APP_HIDE)

    def close(self):
        self._post(WM_APP_CLOSE)

    # --- window thread (needs a desktop) -------------------------------------------------------
    def _main(self):  # pragma: no cover - GUI thread
        import win32api
        import win32con
        import win32gui
        use_physical_pixels()
        try:
            wnd_class = win32gui.WNDCLASS()
            wnd_class.hInstance = win32api.GetModuleHandle(None)
            wnd_class.lpszClassName = "DnDToolsHoverCard"
            wnd_class.lpfnWndProc = self._wnd_proc
            atom = win32gui.RegisterClass(wnd_class)
            ex_style = (win32con.WS_EX_TOPMOST | win32con.WS_EX_LAYERED | win32con.WS_EX_TOOLWINDOW
                        | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_NOACTIVATE)
            self._hwnd = win32gui.CreateWindowEx(ex_style, atom, "DnDToolsHoverCard", win32con.WS_POPUP,
                                                 0, 0, 0, 0, 0, 0, wnd_class.hInstance, None)
        except Exception:
            logger.exception("Hover card window could not be created")
            self._ready.set()
            return
        self._ready.set()
        win32gui.PumpMessages()

    def _show_request(self, hwnd):  # pragma: no cover - GUI thread
        import win32con
        import win32gui
        with self._lock:
            request, self._request = self._request, None
        if request is None:
            return
        card, tooltip, screen, asked = request
        started = time.perf_counter()
        image = self._render(card, screen[1])
        rendered = time.perf_counter()
        x, y = place_panel(image.size, tooltip, screen)
        _blit(hwnd, image, x, y)
        logger.debug("Hover card window: waited %.0f ms, drew %.0f ms, blit %.0f ms", 1000 * (started - asked),
                    1000 * (rendered - started), 1000 * (time.perf_counter() - rendered))
        win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

    def _wnd_proc(self, hwnd, msg, w_param, l_param):  # pragma: no cover - GUI thread
        import win32con
        import win32gui
        try:
            if msg == WM_APP_SHOW:
                self._show_request(hwnd)
                return 0
            if msg == WM_APP_HIDE:
                win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                return 0
            if msg == WM_APP_CLOSE:
                win32gui.DestroyWindow(hwnd)
                return 0
            if msg == win32con.WM_DESTROY:
                win32gui.PostQuitMessage(0)
                return 0
        except Exception:
            logger.exception("Hover card message %s failed", msg)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, w_param, l_param)
