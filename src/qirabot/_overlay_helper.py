"""Overlay helper process: the on-screen progress window itself.

Runs as ``python -m qirabot._overlay_helper``, spawned by
:class:`qirabot.overlay.Overlay`. A separate process because macOS requires
the GUI to own the process main thread, which the user's script already
occupies — a thread cannot host AppKit, a child process can.

Protocol: one JSON object per stdin line.
    {"text": "..."}   replace the window text
    {"cmd": "close"}  exit
stdin EOF also exits, so a dying parent can never leave the window behind.

The window is excluded from screen capture (macOS: NSWindowSharingNone,
verified against the pyautogui/`screencapture` path; Windows:
WDA_EXCLUDEFROMCAPTURE) and is click-through and non-activating, so it
neither appears in bot screenshots nor interferes with input.

Exit codes: 0 normal, 3 unsupported platform or missing GUI dependency.
"""

from __future__ import annotations

import json
import sys
import threading

_WIDTH, _HEIGHT, _MARGIN = 340, 64, 24


def _messages():
    """Yield parsed stdin messages until EOF or an explicit close command."""
    for raw in sys.stdin:
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(msg, dict) or msg.get("cmd") == "close":
            return
        yield msg


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
        for msg in _messages():
            text = msg.get("text")
            if text is not None:
                bridge.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "update:", str(text), False
                )
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
        return 3

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.88)
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
    ex_style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongPtrW(
        hwnd,
        GWL_EXSTYLE,
        ex_style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE,
    )

    q: queue.Queue = queue.Queue()
    _CLOSE = object()

    def reader() -> None:
        for msg in _messages():
            text = msg.get("text")
            if text is not None:
                q.put(str(text))
        q.put(_CLOSE)

    def poll() -> None:
        try:
            while True:
                item = q.get_nowait()
                if item is _CLOSE:
                    root.destroy()
                    return
                label.config(text=item)
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
