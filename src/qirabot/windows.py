"""Zero-dependency Win32 layer for the window-bound desktop backend.

:class:`Window` is the SDK-level target for driving one Windows window::

    bot.run("...", target=Window(title_re="Genshin"))

Everything here is stdlib ``ctypes`` against user32/gdi32 — no pywinauto, no
pip dependencies. The DLLs are reached exclusively through the :func:`_user32`
/ :func:`_gdi32` shims so tests (and non-Windows imports) can substitute
fakes; nothing in this module touches a DLL at import time.

The adapter-facing surface is deliberately small: window resolution, the
client-area rectangle, two capture paths (PrintWindow, full-screen BitBlt
crop), a DPI-awareness guard, foreground management, and SendInput event
builders (scancode, unicode, mouse) + :func:`send_inputs`.
"""

from __future__ import annotations

import ctypes
import sys
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator

from qirabot.exceptions import QirabotError

if TYPE_CHECKING:
    from PIL import Image

# ---------------------------------------------------------------------------
# DLL shims (the single mock point for tests; lazy so import works anywhere)
# ---------------------------------------------------------------------------

_dlls: dict[str, Any] = {}


def _dll(name: str) -> Any:
    if sys.platform != "win32":
        raise QirabotError(
            "the Windows window backend only runs on Windows",
            code="windows.unsupported_platform",
        )
    if name not in _dlls:
        _dlls[name] = ctypes.WinDLL(name, use_last_error=True)
    return _dlls[name]


def _user32() -> Any:
    return _dll("user32")


def _gdi32() -> Any:
    return _dll("gdi32")


# ---------------------------------------------------------------------------
# DPI awareness (shared with recording.window_region)
# ---------------------------------------------------------------------------

# Sentinel HANDLE for SetThreadDpiAwarenessContext; -4 = PER_MONITOR_AWARE_V2.
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4


@contextmanager
def dpi_awareness() -> Iterator[None]:
    """Run the block with the thread per-monitor-DPI-aware (best-effort).

    Win32 coordinate/geometry APIs answer in the thread's DPI space; without
    this a DPI-virtualized process gets scaled-and-lying client rects, so
    clicks and captures drift on >100% displays. Thread-scoped and restored on
    exit so the host process's awareness is never permanently changed
    (pre-1607 Windows lacks the API — then it's a no-op).
    """
    prev = None
    user32 = _user32()
    try:
        try:
            prev = user32.SetThreadDpiAwarenessContext(
                DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            )
        except Exception:
            prev = None
        yield
    finally:
        if prev:
            try:
                user32.SetThreadDpiAwarenessContext(prev)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Window handle
# ---------------------------------------------------------------------------


# WINFUNCTYPE only exists on Windows; CFUNCTYPE is ABI-identical on 64-bit and
# only used off-Windows by tests exercising the enumeration logic with fakes.
_WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)


def list_visible_windows() -> list[tuple[int, str]]:
    """All visible top-level windows with a non-empty title, as (hwnd, title)."""
    user32 = _user32()
    results: list[tuple[int, str]] = []

    @_WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)  # type: ignore[untyped-decorator]
    def enum_proc(hwnd: Any, _lparam: Any) -> int:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if buf.value:
                    results.append((int(hwnd) if hwnd else 0, buf.value))
        return 1  # continue enumeration

    user32.EnumWindows(enum_proc, 0)
    return results


class Window:
    """Handle to one Windows top-level window.

    Args:
        hwnd: explicit window handle (from Spy++, ``qirabot doctor``, or a
            previous resolution).
        title_re: regex matched (``re.search``) against visible window titles;
            exactly one of ``hwnd``/``title_re`` is required. Whole-desktop
            automation belongs to the pyautogui backend instead.
    """

    def __init__(self, hwnd: int | None = None, title_re: str | None = None) -> None:
        if not hwnd and not title_re:
            raise QirabotError(
                "Window needs hwnd= or title_re= (for whole-desktop automation "
                "use the pyautogui backend)",
                code="windows.window_unspecified",
            )
        self._hwnd = int(hwnd) if hwnd else None
        self._title_re = title_re

    def __repr__(self) -> str:
        return f"Window(hwnd={self._hwnd!r}, title_re={self._title_re!r})"

    @property
    def hwnd(self) -> int:
        """The resolved window handle (resolves ``title_re`` on first use)."""
        if self._hwnd is None:
            self._hwnd = self._resolve()
        return self._hwnd

    @property
    def title(self) -> str | None:
        user32 = _user32()
        length = user32.GetWindowTextLengthW(self.hwnd)
        if not length:
            return None
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(self.hwnd, buf, length + 1)
        return buf.value or None

    def _resolve(self) -> int:
        import re

        assert self._title_re is not None
        pattern = re.compile(self._title_re)
        windows = list_visible_windows()
        matches = [(h, t) for h, t in windows if pattern.search(t)]
        if len(matches) == 1:
            return matches[0][0]
        if not matches:
            titles = ", ".join(repr(t) for _, t in windows[:20]) or "none"
            raise QirabotError(
                f"no visible window title matches {self._title_re!r} "
                f"(visible windows: {titles})",
                code="windows.window_not_found",
            )
        listing = ", ".join(f"{t!r} (hwnd={h})" for h, t in matches[:10])
        raise QirabotError(
            f"{len(matches)} windows match {self._title_re!r}: {listing} — "
            "narrow the regex or pass hwnd=",
            code="windows.window_ambiguous",
        )


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def client_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Client area of ``hwnd`` as screen-space ``(x, y, w, h)`` physical pixels.

    Call under :func:`dpi_awareness`. The client area is what the adapter
    screenshots, so model coordinates are client-relative pixels.
    """
    user32 = _user32()
    rect = _RECT()
    if not user32.GetClientRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
        raise QirabotError(
            f"GetClientRect failed for hwnd={hwnd} (window closed?)",
            code="windows.window_gone",
        )
    origin = _POINT(0, 0)
    user32.ClientToScreen(ctypes.c_void_p(hwnd), ctypes.byref(origin))
    return origin.x, origin.y, rect.right - rect.left, rect.bottom - rect.top


# GetSystemMetrics indices for the virtual desktop (all monitors' bounding box).
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


def virtual_screen() -> tuple[int, int, int, int]:
    """Virtual-desktop bounds ``(x, y, w, h)`` — the origin can be NEGATIVE
    (a monitor left of / above the primary), which the normalization in the
    adapter must subtract, not clamp."""
    user32 = _user32()
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

_PW_RENDERFULLCONTENT = 0x00000002  # DWM-composited content (Win 8.1+)
_SRCCOPY = 0x00CC0020
_DIB_RGB_COLORS = 0
_BI_RGB = 0


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


def _bitmap_to_image(mem_dc: Any, bitmap: Any, w: int, h: int) -> "Image.Image":
    """Read a selected 32-bit bitmap out of ``mem_dc`` into a PIL image."""
    from PIL import Image

    gdi32 = _gdi32()
    info = _BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    info.bmiHeader.biWidth = w
    info.bmiHeader.biHeight = -h  # negative = top-down rows
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = _BI_RGB
    buf = ctypes.create_string_buffer(w * h * 4)
    if not gdi32.GetDIBits(mem_dc, bitmap, 0, h, buf, ctypes.byref(info), _DIB_RGB_COLORS):
        raise QirabotError("GetDIBits failed", code="windows.capture_failed")
    return Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)


@contextmanager
def _mem_bitmap(src_dc: Any, w: int, h: int) -> Iterator[tuple[Any, Any]]:
    """A memory DC with a ``w``x``h`` bitmap selected, cleaned up on exit."""
    gdi32 = _gdi32()
    mem_dc = gdi32.CreateCompatibleDC(src_dc)
    bitmap = gdi32.CreateCompatibleBitmap(src_dc, w, h)
    try:
        gdi32.SelectObject(mem_dc, bitmap)
        yield mem_dc, bitmap
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)


def capture_window(hwnd: int) -> "Image.Image | None":
    """Capture ``hwnd``'s client area via PrintWindow, or None if it failed.

    PW_RENDERFULLCONTENT asks DWM for composited content, which covers most
    modern apps even when occluded. DirectX-exclusive windows still come back
    black/failed — the caller falls back to :func:`capture_screen_region`.
    """
    user32, _ = _user32(), _gdi32()
    _, _, w, h = client_rect(hwnd)
    if w <= 0 or h <= 0:
        return None
    window_dc = user32.GetWindowDC(ctypes.c_void_p(hwnd))
    if not window_dc:
        return None
    try:
        with _mem_bitmap(window_dc, w, h) as (mem_dc, bitmap):
            # PW_CLIENTONLY (1) | PW_RENDERFULLCONTENT: client area only, so
            # the image matches the coordinate space actions use.
            if not user32.PrintWindow(
                ctypes.c_void_p(hwnd), mem_dc, 1 | _PW_RENDERFULLCONTENT
            ):
                return None
            img = _bitmap_to_image(mem_dc, bitmap, w, h)
    finally:
        user32.ReleaseDC(ctypes.c_void_p(hwnd), window_dc)
    # All-black usually means a GPU-composited window PrintWindow can't see.
    if img.getbbox() is None:
        return None
    return img


def capture_screen_region(x: int, y: int, w: int, h: int) -> "Image.Image":
    """Capture a screen rectangle via BitBlt from the desktop DC.

    Captures whatever is composited on screen (works for DirectX windows in
    the foreground); physical pixels, virtual-desktop coordinates.
    """
    user32, gdi32 = _user32(), _gdi32()
    screen_dc = user32.GetDC(None)
    if not screen_dc:
        raise QirabotError("GetDC(desktop) failed", code="windows.capture_failed")
    try:
        with _mem_bitmap(screen_dc, w, h) as (mem_dc, bitmap):
            if not gdi32.BitBlt(mem_dc, 0, 0, w, h, screen_dc, x, y, _SRCCOPY):
                raise QirabotError("BitBlt failed", code="windows.capture_failed")
            return _bitmap_to_image(mem_dc, bitmap, w, h)
    finally:
        user32.ReleaseDC(None, screen_dc)


# ---------------------------------------------------------------------------
# SendInput
# ---------------------------------------------------------------------------

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

# KEYBDINPUT flags
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

# MOUSEINPUT flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

WHEEL_DELTA = 120

_ULONG_PTR = ctypes.c_size_t


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_uint16),
        ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("union", _INPUTUNION)]

    # Introspection sugar so tests (and repr-debugging) read naturally.
    @property
    def mi(self) -> _MOUSEINPUT:
        mi: _MOUSEINPUT = self.union.mi
        return mi

    @property
    def ki(self) -> _KEYBDINPUT:
        ki: _KEYBDINPUT = self.union.ki
        return ki


def key_scancode_event(scancode: int, extended: bool, up: bool) -> INPUT:
    """A DirectInput-visible key event (games read these; virtual keys they don't)."""
    flags = KEYEVENTF_SCANCODE
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    if up:
        flags |= KEYEVENTF_KEYUP
    ev = INPUT(type=INPUT_KEYBOARD)
    ev.union.ki = _KEYBDINPUT(wVk=0, wScan=scancode, dwFlags=flags, time=0, dwExtraInfo=0)
    return ev


def key_unicode_events(char: str, up: bool) -> list[INPUT]:
    """KEYEVENTF_UNICODE event(s) for one character (surrogate pair aware)."""
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
    encoded = char.encode("utf-16-le")
    events = []
    for i in range(0, len(encoded), 2):
        unit = int.from_bytes(encoded[i : i + 2], "little")
        ev = INPUT(type=INPUT_KEYBOARD)
        ev.union.ki = _KEYBDINPUT(wVk=0, wScan=unit, dwFlags=flags, time=0, dwExtraInfo=0)
        events.append(ev)
    return events


def mouse_event(
    flags: int, dx: int = 0, dy: int = 0, data: int = 0
) -> INPUT:
    ev = INPUT(type=INPUT_MOUSE)
    ev.union.mi = _MOUSEINPUT(
        dx=dx, dy=dy, mouseData=ctypes.c_uint32(data & 0xFFFFFFFF).value,
        dwFlags=flags, time=0, dwExtraInfo=0,
    )
    return ev


def _last_error() -> int:
    getter = getattr(ctypes, "get_last_error", None)
    return int(getter()) if getter else 0


def send_inputs(events: list[INPUT]) -> None:
    """Inject events atomically via one SendInput call."""
    if not events:
        return
    array = (INPUT * len(events))(*events)
    sent = _user32().SendInput(len(events), array, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise QirabotError(
            f"SendInput injected {sent}/{len(events)} events "
            f"(err={_last_error()})",
            code="windows.sendinput_failed",
        )


# ---------------------------------------------------------------------------
# Foreground management
# ---------------------------------------------------------------------------

_SW_RESTORE = 9


def ensure_foreground(hwnd: int) -> bool:
    """Bring ``hwnd`` to the foreground (best-effort; returns success).

    Games only receive DirectInput while foreground. SetForegroundWindow is
    refused unless our process owns the current foreground input; the standard
    unlock is injecting a no-op ALT tap first. A minimized window also needs
    SW_RESTORE before it can take focus.
    """
    user32 = _user32()
    if user32.GetForegroundWindow() == hwnd:
        return True
    user32.ShowWindow(ctypes.c_void_p(hwnd), _SW_RESTORE)
    user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
    if user32.GetForegroundWindow() == hwnd:
        return True
    # ALT tap unlocks SetForegroundWindow for this process, then retry.
    alt = 0x38  # LALT scancode
    send_inputs([key_scancode_event(alt, False, False), key_scancode_event(alt, False, True)])
    user32.SetForegroundWindow(ctypes.c_void_p(hwnd))
    time.sleep(0.05)
    return bool(user32.GetForegroundWindow() == hwnd)
