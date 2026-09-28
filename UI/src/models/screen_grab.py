"""Fast screen captures of just the pixels asked for.

PIL's ImageGrab copies the whole desktop and then crops it, which costs ~70-130 ms at 4K even for a
small box. A GDI BitBlt of the region itself costs about its size instead: a 64 px wide strip down
the screen takes ~5 ms. Coordinates are physical screen pixels (see hover_panel.use_physical_pixels).
"""
import ctypes
from ctypes import wintypes

import numpy as np

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0


class BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class BitmapInfo(ctypes.Structure):
    _fields_ = [("bmiHeader", BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 3)]


def top_down_32bpp(width, height):
    """BITMAPINFO for a 32-bit DIB whose first row is the top one."""
    info = BitmapInfo()
    info.bmiHeader.biSize = ctypes.sizeof(BitmapInfoHeader)
    info.bmiHeader.biWidth, info.bmiHeader.biHeight = width, -height
    info.bmiHeader.biPlanes, info.bmiHeader.biBitCount = 1, 32
    return info


def gdi():  # pragma: no cover - Windows only
    """user32/gdi32 with handle-safe signatures (64-bit handles must not be truncated to int)."""
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BitmapInfo), wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    return user32, gdi32


def grab(region):  # pragma: no cover - needs a desktop
    """The screen's pixels in `region` (left, top, right, bottom) as an RGB array (height, width, 3)."""
    left, top, right, bottom = (int(v) for v in region)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return np.zeros((max(height, 0), max(width, 0), 3), dtype=np.uint8)
    user32, gdi32 = gdi()
    screen_dc = user32.GetDC(None)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(memory_dc, ctypes.byref(top_down_32bpp(width, height)), DIB_RGB_COLORS,
                                    ctypes.byref(bits), None, 0)
    try:
        old = gdi32.SelectObject(memory_dc, bitmap)
        gdi32.BitBlt(memory_dc, 0, 0, width, height, screen_dc, left, top, SRCCOPY)
        gdi32.SelectObject(memory_dc, old)
        bgra = np.ctypeslib.as_array(ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint8)), shape=(height, width, 4))
        return bgra[..., 2::-1].copy()  # copy: the DIB is freed below
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)
