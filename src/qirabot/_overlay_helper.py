"""Overlay helper process: the on-screen progress window itself.

Runs as ``python -m qirabot._overlay_helper``, spawned by
:class:`qirabot.overlay.Overlay`. A separate process because macOS requires
the GUI to own the process main thread, which the user's script already
occupies — a thread cannot host AppKit, a child process can.

Protocol: one JSON object per stdin line.
    {"text": "..."}                  replace the window text
    {"cmd": "close", "linger": 1.5}  exit after `linger` seconds (default 0),
                                     so the final ✓/✗ text is readable
stdin EOF also exits, so a dying parent can never leave the window behind.

The window is excluded from screen capture (macOS: NSWindowSharingNone,
verified against the pyautogui/`screencapture` path; Windows:
WDA_EXCLUDEFROMCAPTURE) and is click-through and non-activating, so it
neither appears in bot screenshots nor interferes with input.

Exit codes: 0 normal, 3 unsupported platform or missing GUI dependency.
"""

from __future__ import annotations

import io
import json
import sys
import threading
import time

_WIDTH, _HEIGHT, _MARGIN = 340, 88, 24


def _read_stdin(on_text):
    """Feed stdin texts to ``on_text``; return the close command's linger
    seconds (0.0 on EOF or a malformed value)."""
    # Explicit UTF-8: sys.stdin's default pipe encoding follows the locale
    # (GBK on Chinese Windows), which would garble any non-ASCII sender.
    # The parent sends ASCII-escaped JSON, so this is belt and braces.
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    for raw in stdin:
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        if msg.get("cmd") == "close":
            try:
                return max(0.0, float(msg.get("linger", 0)))
            except (TypeError, ValueError):
                return 0.0
        text = msg.get("text")
        if text is not None:
            on_text(str(text))
    return 0.0


def _run_macos() -> int:
    try:
        import AppKit
    except ImportError:
        return 3

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    screen = AppKit.NSScreen.mainScreen().frame()
    # NSWindow origin is bottom-left: this is the bottom-right corner.
    rect = AppKit.NSMakeRect(
        screen.size.width - _WIDTH - _MARGIN, _MARGIN, _WIDTH, _HEIGHT
    )
    style = (
        AppKit.NSWindowStyleMaskBorderless
        | AppKit.NSWindowStyleMaskNonactivatingPanel
    )
    panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, style, AppKit.NSBackingStoreBuffered, False
    )
    panel.setSharingType_(AppKit.NSWindowSharingNone)
    panel.setOpaque_(False)
    panel.setBackgroundColor_(AppKit.NSColor.clearColor())
    panel.setLevel_(AppKit.NSStatusWindowLevel)
    panel.setIgnoresMouseEvents_(True)
    panel.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        | AppKit.NSWindowCollectionBehaviorStationary
        | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
    )

    content = panel.contentView()
    content.setWantsLayer_(True)
    content.layer().setCornerRadius_(10.0)
    content.layer().setBackgroundColor_(
        AppKit.NSColor.colorWithCalibratedWhite_alpha_(0.08, 0.85).CGColor()
    )

    label = AppKit.NSTextField.alloc().initWithFrame_(
        AppKit.NSMakeRect(12, 8, _WIDTH - 24, _HEIGHT - 16)
    )
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setTextColor_(AppKit.NSColor.whiteColor())
    label.setFont_(AppKit.NSFont.systemFontOfSize_(12))
    label.cell().setTruncatesLastVisibleLine_(True)
    label.setStringValue_("qirabot")
    content.addSubview_(label)
    panel.orderFrontRegardless()

    # AppKit views may only be touched from the main thread, which app.run()
    # owns below — the stdin reader hands updates over with
    # performSelectorOnMainThread instead of calling the view directly.
    class _Bridge(AppKit.NSObject):
        def update_(self, text):
            label.setStringValue_(text)

        def quit_(self, _sender):
            app.terminate_(None)

    bridge = _Bridge.alloc().init()

    def reader() -> None:
        linger = _read_stdin(
            lambda text: bridge.performSelectorOnMainThread_withObject_waitUntilDone_(
                "update:", text, False
            )
        )
        if linger:
            time.sleep(linger)
        bridge.performSelectorOnMainThread_withObject_waitUntilDone_(
            "quit:", None, False
        )

    threading.Thread(target=reader, daemon=True).start()
    app.run()
    return 0


def _run_windows() -> int:
    import ctypes
    import queue

    try:
        import tkinter as tk
    except ImportError:
        # e.g. a Microsoft Store / embedded Python without tcl-tk.
        return 3

    # Per-monitor DPI awareness, before any window exists: without it the
    # process is scaled by the system and the bottom-right placement lands
    # away from the corner on >100% displays. Best-effort (needs Win 8.1+).
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.88)  # also makes the window WS_EX_LAYERED,
    # which WDA_EXCLUDEFROMCAPTURE requires
    root.configure(bg="#141414")
    label = tk.Label(
        root, text="qirabot", fg="white", bg="#141414",
        font=("Segoe UI", 10), justify="left", anchor="w",
        wraplength=_WIDTH - 24, padx=12, pady=8,
    )
    label.pack(fill="both", expand=True)
    # Extra bottom margin keeps the window clear of the taskbar.
    x = root.winfo_screenwidth() - _WIDTH - _MARGIN
    y = root.winfo_screenheight() - _HEIGHT - _MARGIN - 48
    root.geometry(f"{_WIDTH}x{_HEIGHT}+{x}+{y}")
    root.update_idletasks()

    user32 = ctypes.windll.user32
    HWND = ctypes.c_void_p  # pointer-sized, so 64-bit handles don't truncate
    user32.GetAncestor.argtypes = [HWND, ctypes.c_uint]
    user32.GetAncestor.restype = HWND
    user32.SetWindowDisplayAffinity.argtypes = [HWND, ctypes.c_uint]
    # 32-bit user32 doesn't export the *Ptr variants (they're macros there);
    # ex-style values fit in 32 bits either way.
    get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    get_long.argtypes = [HWND, ctypes.c_int]
    set_long.argtypes = [HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowPos.argtypes = [
        HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_uint,
    ]

    # winfo_id() is a Tk child window; the display affinity and the
    # click-through styles must go on the top-level ancestor.
    hwnd = user32.GetAncestor(root.winfo_id(), 2)  # GA_ROOT
    WDA_EXCLUDEFROMCAPTURE = 0x11  # Win10 2004+
    WDA_MONITOR = 0x01  # older fallback: black box in captures, never content
    if not user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
        user32.SetWindowDisplayAffinity(hwnd, WDA_MONITOR)
    GWL_EXSTYLE = -20
    WS_EX_TRANSPARENT = 0x00000020  # clicks pass through to what's below
    WS_EX_TOOLWINDOW = 0x00000080  # no taskbar / Alt-Tab entry
    WS_EX_LAYERED = 0x00080000
    WS_EX_NOACTIVATE = 0x08000000  # never steals focus from the target app
    ex_style = get_long(hwnd, GWL_EXSTYLE)
    set_long(
        hwnd,
        GWL_EXSTYLE,
        ex_style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE,
    )
    # SetWindowLong alone doesn't reliably apply style changes to a window
    # that is already visible; SWP_FRAMECHANGED forces the recalculation.
    HWND_TOPMOST = HWND(-1)
    SWP_NOSIZE, SWP_NOMOVE = 0x0001, 0x0002
    SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0010, 0x0020
    user32.SetWindowPos(
        hwnd, HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )

    q: queue.Queue = queue.Queue()
    _CLOSE = "close"

    def reader() -> None:
        linger = _read_stdin(lambda text: q.put(("text", text)))
        q.put((_CLOSE, linger))

    def poll() -> None:
        try:
            while True:
                kind, value = q.get_nowait()
                if kind is _CLOSE:
                    root.after(int(value * 1000), root.destroy)
                    return
                label.config(text=value)
        except queue.Empty:
            pass
        root.after(100, poll)

    threading.Thread(target=reader, daemon=True).start()
    root.after(100, poll)
    root.mainloop()
    return 0


def main() -> int:
    if sys.platform == "darwin":
        return _run_macos()
    if sys.platform == "win32":
        return _run_windows()
    return 3


if __name__ == "__main__":
    sys.exit(main())
