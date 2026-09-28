"""A small always-on-top panel beside the game's item tooltip, showing the item's value.

A native layered window, like DnDTools' sort overlay: topmost, click-through, and only ever shown
with SW_SHOWNOACTIVATE, so the game keeps focus and every input. Its own thread runs the window's
message loop; show/hide only store the request and post a message.
"""
import logging
import threading

logger = logging.getLogger(__name__)

GAP_PX = 12
PADDING_PX = 14      # at 1080p; scaled with the screen
LINE_GAP_PX = 3
OPACITY = 240
BACKGROUND, BORDER = (21, 17, 15), (138, 109, 42)
STYLES = {  # style -> (colour, font px at 1080p, bold)
    "value": ((228, 200, 105), 22, True),
    "detail": ((216, 208, 192), 15, False),
    "verdict": ((156, 204, 101), 16, True),
    "muted": ((154, 154, 154), 16, False),
    "warning": ((255, 183, 77), 14, False),
}
WM_APP_SHOW, WM_APP_HIDE, WM_APP_CLOSE = 0x8001, 0x8002, 0x8003
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4


def use_physical_pixels():
    """Make this thread see real screen pixels. With display scaling (e.g. 150% on 4K), a
    DPI-unaware thread gets scaled cursor positions and screen sizes that don't match captures."""
    try:
        import ctypes
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
    except (AttributeError, OSError):  # older Windows: the whole process is usually aware already
        pass


def font_px(base_px, screen_height):
    return max(9, round(base_px * screen_height / 1080))


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


class HoverPanel:
    def __init__(self):
        self._lock = threading.Lock()
        self._request = None     # (lines, tooltip, screen) waiting to be shown
        self._showing = None     # what is on screen
        self._hwnd = None
        self._fonts = {}
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

    def show(self, lines, tooltip, screen):
        self._ensure_started()
        with self._lock:
            self._request = (list(lines), tuple(tooltip), tuple(screen))
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
            wnd_class.lpszClassName = "DnDToolsHoverPanel"
            wnd_class.lpfnWndProc = self._wnd_proc
            wnd_class.hbrBackground = win32gui.CreateSolidBrush(win32api.RGB(*BACKGROUND))
            atom = win32gui.RegisterClass(wnd_class)
            ex_style = (win32con.WS_EX_TOPMOST | win32con.WS_EX_LAYERED | win32con.WS_EX_TOOLWINDOW
                        | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_NOACTIVATE)
            self._hwnd = win32gui.CreateWindowEx(ex_style, atom, "DnDToolsHoverPanel", win32con.WS_POPUP,
                                                 0, 0, 0, 0, 0, 0, wnd_class.hInstance, None)
            win32gui.SetLayeredWindowAttributes(self._hwnd, 0, OPACITY, win32con.LWA_ALPHA)
        except Exception:
            logger.exception("Hover panel window could not be created")
            self._ready.set()
            return
        self._ready.set()
        win32gui.PumpMessages()

    def _font(self, style, screen_height):  # pragma: no cover - GUI thread
        import win32con
        import win32gui
        _, px, bold = STYLES.get(style, STYLES["detail"])
        key = (style, screen_height)
        if key not in self._fonts:
            font = win32gui.LOGFONT()
            font.lfHeight = -font_px(px, screen_height)
            font.lfWeight = win32con.FW_BOLD if bold else win32con.FW_NORMAL
            font.lfQuality = win32con.CLEARTYPE_QUALITY
            font.lfFaceName = "Segoe UI"
            self._fonts[key] = win32gui.CreateFontIndirect(font)
        return self._fonts[key]

    def _layout(self, hwnd, lines, screen_height):  # pragma: no cover - GUI thread
        """[(line, width, height)] and the panel size for `lines`."""
        import win32gui
        hdc = win32gui.GetDC(hwnd)
        try:
            measured = []
            for line in lines:
                old = win32gui.SelectObject(hdc, self._font(line.style, screen_height))
                width, height = win32gui.GetTextExtentPoint32(hdc, line.text)
                win32gui.SelectObject(hdc, old)
                measured.append((line, width, height))
        finally:
            win32gui.ReleaseDC(hwnd, hdc)
        pad = font_px(PADDING_PX, screen_height)
        gap = font_px(LINE_GAP_PX, screen_height)
        width = max((w for _, w, _ in measured), default=0) + 2 * pad
        height = sum(h for _, _, h in measured) + gap * max(len(measured) - 1, 0) + 2 * pad
        return measured, (width, height)

    def _show_request(self, hwnd):  # pragma: no cover - GUI thread
        import win32con
        import win32gui
        with self._lock:
            request, self._request = self._request, None
        if request is None:
            return
        lines, tooltip, screen = request
        measured, size = self._layout(hwnd, lines, screen[1])
        x, y = place_panel(size, tooltip, screen)
        self._showing = (measured, screen[1])
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, x, y, size[0], size[1],
                              win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW)
        win32gui.InvalidateRect(hwnd, None, True)

    def _paint(self, hwnd):  # pragma: no cover - GUI thread
        import win32api
        import win32con
        import win32gui
        hdc, paint = win32gui.BeginPaint(hwnd)
        try:
            rect = win32gui.GetClientRect(hwnd)
            brush = win32gui.CreateSolidBrush(win32api.RGB(*BACKGROUND))
            win32gui.FillRect(hdc, rect, brush)
            win32gui.DeleteObject(brush)
            pen = win32gui.CreatePen(win32con.PS_SOLID, 2, win32api.RGB(*BORDER))
            old_pen = win32gui.SelectObject(hdc, pen)
            old_brush = win32gui.SelectObject(hdc, win32gui.GetStockObject(win32con.NULL_BRUSH))
            win32gui.Rectangle(hdc, rect[0], rect[1], rect[2], rect[3])
            win32gui.SelectObject(hdc, old_brush)
            win32gui.SelectObject(hdc, old_pen)
            win32gui.DeleteObject(pen)
            if self._showing:
                measured, screen_height = self._showing
                pad, gap = font_px(PADDING_PX, screen_height), font_px(LINE_GAP_PX, screen_height)
                win32gui.SetBkMode(hdc, win32con.TRANSPARENT)
                y = pad
                for line, _, height in measured:
                    colour = STYLES.get(line.style, STYLES["detail"])[0]
                    old = win32gui.SelectObject(hdc, self._font(line.style, screen_height))
                    win32gui.SetTextColor(hdc, win32api.RGB(*colour))
                    win32gui.ExtTextOut(hdc, pad, y, 0, None, line.text)
                    win32gui.SelectObject(hdc, old)
                    y += height + gap
        finally:
            win32gui.EndPaint(hwnd, paint)

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
            if msg == win32con.WM_PAINT:
                self._paint(hwnd)
                return 0
            if msg == win32con.WM_ERASEBKGND:
                return 1
            if msg == win32con.WM_DESTROY:
                for font in self._fonts.values():
                    win32gui.DeleteObject(font)
                self._fonts.clear()
                win32gui.PostQuitMessage(0)
                return 0
        except Exception:
            logger.exception("Hover panel message %s failed", msg)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, w_param, l_param)
