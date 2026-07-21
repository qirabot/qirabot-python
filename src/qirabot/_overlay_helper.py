"""Overlay helper process: the on-screen progress window itself.

Runs as ``python -m qirabot._overlay_helper``, spawned by
:class:`qirabot.overlay.Overlay`. A separate process because macOS requires
the GUI to own the process main thread, which the user's script already
occupies — a thread cannot host AppKit, a child process can.

Protocol: one JSON object per stdin line; keys combine freely.
    {"title": "..."}                 the headline (the running instruction)
    {"state": "run" | "ok" | "fail"} status glyph; "run" (re)starts the
                                     elapsed timer, "ok"/"fail" freeze it
    {"text": "..."}                  the body (current step + reasoning)
    {"cmd": "close", "linger": 1.5}  exit after `linger` seconds (default 0),
                                     so the final ✓/✗ state is readable
stdin EOF also exits, so a dying parent can never leave the window behind.

Layout — title row (status glyph · title · elapsed clock) over a wrapping
body. The parent clips every field to a hard character budget before
sending; the labels additionally truncate visually, so oversized CJK text
(wider per char than the budget assumes) degrades to a clean cut, never a
broken layout. The elapsed clock ticks locally, off a 1s timer — it costs
no pipe traffic.

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

_WIDTH, _HEIGHT, _MARGIN = 340, 96, 24

# state -> (glyph, color as #rgb hex, also mapped to NSColor on macOS)
_STATES = {
    "run": ("●", "#f5c542"),   # amber: working
    "ok": ("✓", "#7ddf7d"),    # green: goal reached
    "fail": ("✗", "#f07171"),  # red: goal failed / errored
}


def _read_stdin(on_msg):
    """Feed parsed stdin messages to ``on_msg``; return the close command's
    linger seconds (0.0 on EOF or a malformed value)."""
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
        on_msg(msg)
    return 0.0


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


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

    def _color(hex_rgb: str):
        r, g, b = (int(hex_rgb[i : i + 2], 16) / 255 for i in (1, 3, 5))
        return AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0)

    def _label(frame, font, color=None):
        field = AppKit.NSTextField.alloc().initWithFrame_(frame)
        field.setBezeled_(False)
        field.setDrawsBackground_(False)
        field.setEditable_(False)
        field.setSelectable_(False)
        field.setFont_(font)
        field.setTextColor_(color or AppKit.NSColor.whiteColor())
        content.addSubview_(field)
        return field

    top_y, clock_w = _HEIGHT - 30, 52
    status = _label(
        AppKit.NSMakeRect(12, top_y, 16, 18), AppKit.NSFont.boldSystemFontOfSize_(12)
    )
    title = _label(
        AppKit.NSMakeRect(30, top_y, _WIDTH - 30 - clock_w - 12, 18),
        AppKit.NSFont.boldSystemFontOfSize_(12),
    )
    title.cell().setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
    title.setStringValue_("qirabot")
    try:
        clock_font = AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(
            11, AppKit.NSFontWeightRegular
        )
    except AttributeError:
        clock_font = AppKit.NSFont.systemFontOfSize_(11)
    clock = _label(
        AppKit.NSMakeRect(_WIDTH - clock_w - 12, top_y, clock_w, 18),
        clock_font,
        AppKit.NSColor.colorWithCalibratedWhite_alpha_(0.6, 1.0),
    )
    clock.setAlignment_(AppKit.NSTextAlignmentRight)
    body = _label(
        AppKit.NSMakeRect(12, 8, _WIDTH - 24, _HEIGHT - 42),
        AppKit.NSFont.systemFontOfSize_(12),
    )
    body.cell().setTruncatesLastVisibleLine_(True)
    panel.orderFrontRegardless()

    timer_state = {"t0": None, "frozen": False}

    # AppKit views may only be touched from the main thread, which app.run()
    # owns below — the stdin reader hands updates over with
    # performSelectorOnMainThread instead of calling the views directly.
    class _Bridge(AppKit.NSObject):
        def apply_(self, msg):
            msg = dict(msg)
            if "title" in msg:
                title.setStringValue_(str(msg["title"]))
            state = msg.get("state")
            if state in _STATES:
                glyph, hex_rgb = _STATES[state]
                status.setStringValue_(glyph)
                status.setTextColor_(_color(hex_rgb))
                if state == "run":
                    timer_state.update(t0=time.monotonic(), frozen=False)
                    clock.setStringValue_("0:00")
                else:
                    timer_state["frozen"] = True
            if "text" in msg:
                body.setStringValue_(str(msg["text"]))

        def tick_(self, _timer):
            if timer_state["t0"] is not None and not timer_state["frozen"]:
                clock.setStringValue_(
                    _fmt_elapsed(time.monotonic() - timer_state["t0"])
                )

        def quit_(self, _sender):
            app.terminate_(None)

    bridge = _Bridge.alloc().init()
    AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        1.0, bridge, "tick:", None, True
    )

    def reader() -> None:
        linger = _read_stdin(
            lambda msg: bridge.performSelectorOnMainThread_withObject_waitUntilDone_(
                "apply:", msg, False
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

    BG = "#141414"
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.88)  # also makes the window WS_EX_LAYERED,
    # which WDA_EXCLUDEFROMCAPTURE requires
    root.configure(bg=BG)
    top = tk.Frame(root, bg=BG)
    top.pack(fill="x", padx=12, pady=(8, 0))
    status = tk.Label(top, text="", bg=BG, fg="white", font=("Segoe UI", 10, "bold"))
    status.pack(side="left")
    clock = tk.Label(top, text="", bg=BG, fg="#999999", font=("Consolas", 9))
    clock.pack(side="right")
    # anchor+no wrap: overlong titles clip at the clock's edge instead of
    # pushing it out of the window.
    title = tk.Label(
        top, text="qirabot", bg=BG, fg="white",
        font=("Segoe UI", 10, "bold"), anchor="w",
    )
    title.pack(side="left", fill="x", expand=True, padx=(6, 6))
    body = tk.Label(
        root, text="", bg=BG, fg="white", font=("Segoe UI", 10),
        justify="left", anchor="nw", wraplength=_WIDTH - 24,
    )
    body.pack(fill="both", expand=True, padx=12, pady=(2, 8))
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

    timer_state = {"t0": None, "frozen": False}

    import tkinter.font as tkfont

    title_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")

    def _fit_title(text: str) -> str:
        # tk labels clip at the pixel edge with no truncation cue, so a long
        # instruction just looks complete; trim to the label's real width and
        # add the ellipsis ourselves (macOS gets this for free from
        # NSLineBreakByTruncatingTail). Pixel-based, so CJK/latin mixes trim
        # correctly where a character-count budget could not.
        width = title.winfo_width()
        if width <= 1:  # first message can arrive before layout has run
            width = _WIDTH - 110  # status + clock + paddings
        if title_font.measure(text) <= width:
            return text
        while text and title_font.measure(text + "…") > width:
            text = text[:-1]
        return text + "…"

    def apply(msg: dict) -> None:
        if "title" in msg:
            title.config(text=_fit_title(str(msg["title"])))
        state = msg.get("state")
        if state in _STATES:
            glyph, color = _STATES[state]
            status.config(text=glyph, fg=color)
            if state == "run":
                timer_state.update(t0=time.monotonic(), frozen=False)
                clock.config(text="0:00")
            else:
                timer_state["frozen"] = True
        if "text" in msg:
            body.config(text=str(msg["text"]))

    def tick() -> None:
        if timer_state["t0"] is not None and not timer_state["frozen"]:
            clock.config(text=_fmt_elapsed(time.monotonic() - timer_state["t0"]))
        root.after(1000, tick)

    q: queue.Queue = queue.Queue()
    _CLOSE = "close"

    def reader() -> None:
        linger = _read_stdin(lambda msg: q.put(("msg", msg)))
        q.put((_CLOSE, linger))

    def poll() -> None:
        try:
            while True:
                kind, value = q.get_nowait()
                if kind is _CLOSE:
                    root.after(int(value * 1000), root.destroy)
                    return
                apply(value)
        except queue.Empty:
            pass
        root.after(100, poll)

    threading.Thread(target=reader, daemon=True).start()
    root.after(100, poll)
    root.after(1000, tick)
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
