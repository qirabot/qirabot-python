"""Airtest device adapter for Android, iOS and Windows.

Airtest's normal usage is a global "current device" (``G.DEVICE``) plus
module-level functions (``touch``/``swipe``/``text``), so this adapter is built
to **lazily resolve the current device**: you can pass a concrete ``Device``
instance, the ``airtest.core.api`` module, or the ``G`` global, and every action
reads ``G.DEVICE`` at call time — which also means it follows ``set_current()``
multi-device switches for free.
"""

from __future__ import annotations

import io
import time
from typing import Any

from qirabot.adapters.base import DeviceAdapter, DeviceInfo, ScreenshotConfig, split_combo
from qirabot.exceptions import QirabotError


class AirtestAdapter(DeviceAdapter):
    """Adapter for Airtest devices (``airtest.core.device.Device`` subclasses).

    Accepts three kinds of target:

    * a concrete device instance (e.g. from ``connect_device("Android:///")``),
    * the ``airtest.core.api`` module,
    * the ``airtest.core.helper.G`` global.

    The latter two resolve ``G.DEVICE`` lazily on each call.
    """

    # adb keyevent names for the keys the server may emit. Airtest's keyevent
    # naming is platform-specific (adb on Android, pywinauto on Windows, a tiny
    # set on iOS); this map is Android-first best-effort. Unknown keys pass
    # through unchanged.
    _KEY_MAP = {
        "enter": "ENTER",
        "return": "ENTER",
        "backspace": "KEYCODE_DEL",
        "delete": "KEYCODE_DEL",
        "back": "BACK",
        "home": "HOME",
        "menu": "MENU",
        "tab": "TAB",
        "space": "SPACE",
    }

    # Actions that don't change the screen (or handle their own timing), so the
    # next screenshot needs no settle delay after them. hover is deliberately NOT
    # here: its whole purpose is to reveal delayed UI (tooltips/submenus), so it
    # needs the settle more than most actions, not less.
    _NO_SETTLE = frozenset({"wait", "done", "save_note"})

    # Airtest's device methods don't carry the api-layer ``delay_after_operation()``,
    # so a fixed floor is needed (mirrors the Appium adapter). See
    # ``DeviceAdapter.settle_seconds`` for the override mechanism.
    _SETTLE_SECONDS = 1

    def __init__(self, target: Any) -> None:
        # Do NOT resolve the device here: when the target is the api module / G,
        # the device may not be connected yet (or may be switched later).
        self._target = target
        self._last_size: tuple[int, int] | None = None
        # Held-input tracking for the split press/release primitives (Windows
        # only), so release_all_inputs() can clean up a forgotten release. See
        # DeviceAdapter.release_all_inputs.
        self._held_keys: set[str] = set()
        self._mouse_held = False

    @classmethod
    def accepts(cls, target: Any) -> bool:
        # (b) the airtest.core.api module
        if getattr(target, "__name__", "") == "airtest.core.api":
            return True
        # (c) the G global (a class) — identify by name + module, NEVER touch
        # ``G.DEVICE`` (a metaclass property that raises NoDeviceError before a
        # device is connected, which hasattr would propagate in Python 3).
        if getattr(target, "__name__", "") == "G" and getattr(
            target, "__module__", ""
        ).startswith("airtest."):
            return True
        # (a) a concrete Device instance
        return (
            type(target).__module__.startswith("airtest.")
            and hasattr(target, "snapshot")
            and hasattr(target, "get_current_resolution")
        )

    @property
    def _device(self) -> Any:
        """Resolve the current Airtest device (lazily for module/G targets)."""
        target = self._target
        # Concrete device instance: use as-is.
        if hasattr(target, "snapshot") and hasattr(target, "get_current_resolution"):
            return target
        # Module or G: read G.DEVICE, which raises NoDeviceError (not None) when
        # nothing is connected — convert to a friendly error.
        from airtest.core.error import NoDeviceError

        try:
            return getattr(target, "G", target).DEVICE
        except NoDeviceError as e:
            raise RuntimeError(
                "no current airtest device; call connect_device()/auto_setup() first"
            ) from e

    @property
    def _platform(self) -> str:
        try:
            return (self._device.platform or "").lower()
        except Exception:
            return ""

    @property
    def current_target(self) -> Any:
        # Return the ORIGINAL token (module/G/Device), so callers passing it back
        # keep hitting the same cached adapter and device resolution stays lazy.
        return self._target

    def screenshot(self, config: ScreenshotConfig | None = None) -> bytes:
        cfg = config or ScreenshotConfig()
        from airtest.aircv.utils import cv2_2_pil

        # Airtest's device.snapshot() returns a BGR cv2 ndarray; cv2_2_pil
        # converts BGR -> RGB PIL so we can reuse the shared Pillow pipeline.
        # snapshot() can transiently return None (adb hiccup, minicap restart,
        # Windows window minimized). Retry a few times so a momentary capture
        # failure doesn't surface as OpenCV's !_src.empty() assertion.
        frame = None
        last_exc: Exception | None = None
        for _ in range(3):
            try:
                frame = self._device.snapshot()
            except Exception as e:
                last_exc = e
                frame = None
            if frame is not None and getattr(frame, "size", 1) != 0:
                break
            time.sleep(0.15)
        if frame is None or getattr(frame, "size", 1) == 0:
            raise QirabotError(
                "device snapshot returned empty frame after 3 retries",
                code="airtest.snapshot_empty",
            ) from last_exc
        img = cv2_2_pil(frame)
        img = self._ensure_upright(img)
        self._last_size = (img.width, img.height)
        buf = io.BytesIO()
        if cfg.format == "jpeg":
            # JPEG has no alpha channel; screenshots may be RGBA.
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=cfg.quality)
        else:
            img.save(buf, format="PNG")
        return buf.getvalue()

    def _ensure_upright(self, img: Any) -> Any:
        """Rotate a raw capture so it matches what's physically on screen.

        Only the minicap capture backend rotates frames to the current display
        orientation; the javacap/adbcap fallbacks return the device's *native*
        framebuffer unrotated. On a portrait-natural device running a landscape
        app, that fallback frame is a portrait image holding sideways landscape
        content. The model then reasons about (and clicks) a rotated image while
        ``device.touch`` expects upright coordinates (it applies ``up_2_ori``
        for the orientation) — so every tap lands in the wrong place.

        Rotating the fallback frame to upright here makes the image the model
        sees agree with the coordinate space ``device.touch`` already assumes.
        No touch-side change is needed.

        Guarded to a strict no-op outside that broken case:
        * non-Android platforms are left untouched;
        * portrait displays (orientation 0/2) are left untouched;
        * a frame that is already landscape (w > h, e.g. minicap working, or a
          landscape-natural device) is left untouched, so we never double-rotate.
        """
        if self._platform != "android":
            return img
        try:
            ori = int(self._device.display_info.get("orientation", 0) or 0)
        except Exception:
            return img
        # orientation 1 = 90deg, 3 = 270deg (landscape); 0/2 are portrait.
        if ori not in (1, 3) or img.height <= img.width:
            return img
        from PIL import Image

        # ROTATE_270 is a 90deg clockwise turn (verified against airtest's
        # up_2_ori for orientation 1); orientation 3 is the mirror case.
        return img.transpose(
            Image.Transpose.ROTATE_270 if ori == 1 else Image.Transpose.ROTATE_90
        )

    # Harden Windows clicks: airtest presses immediately after teleporting the
    # cursor and holds only ~10ms, so apps that hit-test on WM_MOUSEMOVE or
    # debounce fast clicks miss it. ``offset`` injects move events before the
    # press, ``duration`` lengthens the hold; coordinates (accuracy) unchanged.
    _WIN_CLICK_OFFSET = 2
    _WIN_CLICK_DURATION = 0.1

    def click(self, x: float, y: float) -> None:
        pos = (int(x), int(y))
        if self._platform == "windows":
            self._device.touch(
                pos, offset=self._WIN_CLICK_OFFSET, duration=self._WIN_CLICK_DURATION
            )
        else:
            self._device.touch(pos)

    def double_click(self, x: float, y: float) -> None:
        pos = (int(x), int(y))
        try:
            self._device.double_click(pos)
        except Exception:
            # Not every platform implements double_click; fall back to two taps.
            self._device.touch(pos)
            self._device.touch(pos)

    def long_press(self, x: float, y: float, duration: float = 2.0) -> None:
        # Airtest's touch() takes a `duration` (seconds) that holds the finger
        # down — the canonical long-press primitive across its backends.
        self._device.touch((int(x), int(y)), duration=duration)

    # Scancode names for airtest's Windows key_press/key_release (DirectInput).
    # Wire key names are lowercased then looked up here; unmapped single
    # letters/digits pass through uppercased ("w" -> "W").
    _WIN_SCANCODES = {
        "enter": "ENTER", "return": "ENTER", "escape": "ESCAPE", "esc": "ESCAPE",
        "space": "SPACE", "tab": "TAB", "backspace": "BACKSPACE", "delete": "DELETE",
        "shift": "LSHIFT", "ctrl": "LCTRL", "control": "LCTRL",
        "alt": "LALT", "option": "LALT",
        "win": "LWINDOWS", "super": "LWINDOWS", "meta": "LWINDOWS",
        "cmd": "LWINDOWS", "command": "LWINDOWS",
        "up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT",
        "arrowup": "UP", "arrowdown": "DOWN", "arrowleft": "LEFT", "arrowright": "RIGHT",
        "home": "HOME", "end": "END", "pageup": "PAGE_UP", "pagedown": "PAGE_DOWN",
    }

    def _scancode(self, key: str) -> str:
        return self._WIN_SCANCODES.get(key.lower(), key.upper())

    def _require_windows(self, action: str) -> None:
        # The split press/release primitives are mouse/keyboard concepts: only
        # the Windows backend has them (touch platforms never get these tools).
        if self._platform != "windows":
            raise NotImplementedError(
                f"airtest {self._platform or 'device'} does not support {action}"
            )

    def mouse_down(self, x: float, y: float) -> None:
        self._require_windows("mouse_down")
        # airtest's mouse_down() presses at the CURRENT cursor, so move first.
        self._device.mouse_move((int(x), int(y)))
        self._device.mouse_down()
        self._mouse_held = True

    def mouse_up(self, x: float | None = None, y: float | None = None) -> None:
        self._require_windows("mouse_up")
        if x is not None and y is not None:
            self._device.mouse_move((int(x), int(y)))
        self._device.mouse_up()
        self._mouse_held = False

    def key_down(self, key: str) -> None:
        self._require_windows("key_down")
        code = self._scancode(key)
        self._device.key_press(code)
        self._held_keys.add(code)

    def key_up(self, key: str) -> None:
        self._require_windows("key_up")
        code = self._scancode(key)
        self._device.key_release(code)
        self._held_keys.discard(code)

    def release_all_inputs(self) -> None:
        # Best-effort sweep; one stuck input must not block releasing the rest.
        if self._held_keys or self._mouse_held:
            dev = self._device
            for code in list(self._held_keys):
                try:
                    dev.key_release(code)
                except Exception:
                    pass
            self._held_keys.clear()
            if self._mouse_held:
                try:
                    dev.mouse_up()
                except Exception:
                    pass
                self._mouse_held = False

    def right_click(self, x: float, y: float) -> None:
        if self._platform == "windows":
            self._device.touch((int(x), int(y)), right_click=True)
        else:
            self.click(x, y)

    def hover(self, x: float, y: float) -> None:
        # Hover is a cursor concept: only Windows has one here (the server never
        # offers hover to touch platforms, so Android/iOS keep the base no-op).
        # Use mouse_move (move only the cursor) — NOT device.move, which
        # relocates the window. hover settles like other actions (it is NOT in
        # _NO_SETTLE), giving hover-triggered UI (submenus, tooltips) time to
        # render before the next screenshot.
        if self._platform == "windows":
            self._device.mouse_move((int(x), int(y)))

    # US-layout ASCII -> scancode names for Windows type_text. Shifted chars
    # hold LSHIFT around the base key; plain symbols/space map directly.
    _SHIFT_CHARS = {
        "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7",
        "*": "8", "(": "9", ")": "0", "_": "-", "+": "=", "{": "[", "}": "]",
        "|": "BACKSLASH", ":": ";", '"': "'", "~": "`", "<": ",", ">": ".", "?": "/",
    }
    _SYMBOL_CHARS = {
        "-": "-", "=": "=", "[": "[", "]": "]", "\\": "BACKSLASH", ";": ";",
        "'": "'", "`": "`", ",": ",", ".": ".", "/": "/", " ": "SPACE",
    }

    # Pacing for the DirectInput scancode paths. SendInput itself has zero
    # delay, so an unpaced press→release is down for well under a millisecond —
    # apps that poll keyboard state per frame (games at 60fps sample every
    # ~16.7ms) skip the key entirely. ≥20ms of hold guarantees at least one
    # frame samples the key as down; the inter-key gap keeps distinct
    # keystrokes in distinct frames.
    _WIN_KEY_HOLD = 0.025
    _WIN_KEY_GAP = 0.025
    # Delay between the focusing tap and the first keystroke, so focus
    # animations/IME activation finish before characters start arriving.
    _FOCUS_SETTLE = 0.3

    def _char_scancode(self, ch: str) -> tuple[bool, str] | None:
        """ASCII char -> (needs_shift, scancode name), or None if not typeable."""
        if "a" <= ch <= "z":
            return False, ch.upper()
        if "A" <= ch <= "Z":
            return True, ch
        if "0" <= ch <= "9":
            return False, ch
        if ch in self._SYMBOL_CHARS:
            return False, self._SYMBOL_CHARS[ch]
        if ch in self._SHIFT_CHARS:
            return True, self._SHIFT_CHARS[ch]
        return None

    def type_text(self, x: float, y: float, text: str) -> None:
        self._device.touch((int(x), int(y)))
        time.sleep(self._FOCUS_SETTLE)
        # Windows: type ASCII via DirectInput scancodes so games (which read raw
        # scancodes and ignore the virtual keys SendKeys sends) receive the text.
        # Any non-ASCII / unmappable char makes the WHOLE string fall back to
        # device.text() (SendKeys) so ordering stays correct. Scancodes are
        # US-layout physical keys; non-US layouts rely on the SendKeys fallback.
        if self._platform == "windows":
            codes = []
            for ch in text:
                m = self._char_scancode(ch)
                if m is None:
                    break
                codes.append(m)
            if text and len(codes) == len(text):
                dev = self._device
                for needs_shift, code in codes:
                    if needs_shift:
                        dev.key_press("LSHIFT")
                    dev.key_press(code)
                    time.sleep(self._WIN_KEY_HOLD)
                    dev.key_release(code)
                    if needs_shift:
                        dev.key_release("LSHIFT")
                    time.sleep(self._WIN_KEY_GAP)
                return
        # enter=False: Android/iOS text() auto-appends Enter by default; the
        # base execute() controls Enter via press_enter instead. (Windows
        # ignores enter and never appends one, so this is safe everywhere.)
        self._device.text(text, enter=False)

    def clear_text(self, x: float, y: float) -> None:
        # Airtest has no element model, so there's no reliable clear primitive.
        # Best effort on Android: move caret to end, then delete repeatedly.
        if self._platform == "android":
            self._device.touch((int(x), int(y)))
            dev = self._device
            try:
                dev.keyevent("KEYCODE_MOVE_END")
            except Exception:
                pass
            # `input keyevent` accepts multiple keycodes per invocation, so one
            # adb round-trip clears the field instead of 64 (each keyevent()
            # call is a full adb shell round-trip, ~2-5s total).
            try:
                dev.adb.shell("input keyevent " + " ".join(["KEYCODE_DEL"] * 64))
            except Exception:
                for _ in range(64):
                    dev.keyevent("KEYCODE_DEL")
        else:
            super().clear_text(x, y)

    # Windows keyevent() forwards to pywinauto keyboard.SendKeys() (verified in
    # airtest/core/win/win.py), whose syntax is: ^ = ctrl, % = alt, + = shift,
    # and named keys in braces ({ENTER}, {TAB}, ...). A bare "ENTER" there would
    # type the letters E-N-T-E-R, so single special keys must be braced too.
    _WIN_MODS = {"ctrl": "^", "control": "^", "alt": "%", "option": "%", "shift": "+"}
    # An unmapped special key is worse than a no-op here: SendKeys would TYPE the
    # name (e.g. "f5" -> the letters f,5), so every key the model emits for a
    # desktop hotkey must be spelled out. F13-F24/numpad/media keys are omitted:
    # the model doesn't emit them for GUI automation.
    _WIN_KEYS = {
        "enter": "{ENTER}", "return": "{ENTER}", "tab": "{TAB}", "escape": "{ESC}",
        "esc": "{ESC}", "backspace": "{BACKSPACE}", "delete": "{DELETE}", "del": "{DELETE}",
        "space": "{SPACE}", "insert": "{INSERT}", "ins": "{INSERT}",
        "arrowup": "{UP}", "arrowdown": "{DOWN}", "arrowleft": "{LEFT}", "arrowright": "{RIGHT}",
        "up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}",
        "pageup": "{PGUP}", "pagedown": "{PGDN}", "pgup": "{PGUP}", "pgdn": "{PGDN}",
        "home": "{HOME}", "end": "{END}",
        **{"f%d" % i: "{F%d}" % i for i in range(1, 13)},
    }

    # Names airtest's key_press/key_release accept as DirectInput scancodes
    # (KEYS + EXTENDED_KEYS in airtest/core/win/ctypesinput.py). Keys outside
    # this set fall back to SendKeys.
    _WIN_SCANCODE_KEYS = frozenset(
        {
            "ESCAPE", "BACKSPACE", "TAB", "ENTER", "SPACE", "CAPS_LOCK",
            "NUM_LOCK", "SCROLL_LOCK", "PRINT_SCREEN", "PAUSE",
            "LCTRL", "RCTRL", "LSHIFT", "RSHIFT", "LALT", "RALT",
            "LWINDOWS", "RWINDOWS", "MENU",
            "UP", "DOWN", "LEFT", "RIGHT",
            "HOME", "END", "PAGE_UP", "PAGE_DOWN", "INSERT", "DELETE",
            "-", "=", "[", "]", ";", "'", "`", ",", ".", "/", "*", "BACKSLASH",
            "NUMPAD_-", "NUMPAD_+", "NUMPAD_.", "NUMPAD_/", "NUMPAD_ENTER",
        }
        | set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        | set("0123456789")
        | {f"F{i}" for i in range(1, 13)}
        | {f"NUMPAD_{i}" for i in range(10)}
    )

    def _scancode_supported(self, keys: list[str]) -> bool:
        return all(self._scancode(k) in self._WIN_SCANCODE_KEYS for k in keys)

    def press_key(self, key: str) -> None:
        mods, base = split_combo(key)
        # Windows: prefer the DirectInput scancode path. Games read raw scancodes
        # and ignore the virtual-key codes SendKeys injects, so keyevent() keys
        # silently no-op in them (` console, WASD, ...). Fall back to SendKeys
        # only for keys the scancode table can't express (e.g. '!', F13+).
        if self._platform == "windows":
            if self._scancode_supported(mods + [base]):
                # Hold mods around the base, release in reverse; key_down/key_up
                # let release_all_inputs sweep up a stuck key. Pace with
                # _WIN_KEY_HOLD so frame-polling apps sample the mods as held
                # before the base lands, and the base as down at all.
                for m in mods:
                    self.key_down(m)
                if mods:
                    time.sleep(self._WIN_KEY_HOLD)
                self.key_down(base)
                time.sleep(self._WIN_KEY_HOLD)
                self.key_up(base)
                for m in reversed(mods):
                    self.key_up(m)
                return
            prefix = "".join(self._WIN_MODS.get(m.lower(), "") for m in mods)
            self._device.keyevent(prefix + self._WIN_KEYS.get(base.lower(), base))
            return
        name = self._KEY_MAP.get(base.lower(), base)
        self._device.keyevent(name)

    def drag(self, from_x: float, from_y: float, to_x: float, to_y: float) -> None:
        self._device.swipe(
            (int(from_x), int(from_y)), (int(to_x), int(to_y)), duration=0.5
        )

    def scroll(self, x: float, y: float, direction: str, distance: int) -> None:
        # DeviceAdapter contract / direct callers keep the legacy ×100 unit; a
        # zero anchor falls back to screen center.
        info = self.device_info()
        cx = x or info.width / 2.0
        cy = y or info.height / 2.0
        self._swipe(cx, cy, direction, distance * 100, info)

    def _scroll_action(self, action_type: str, params: dict[str, Any]) -> None:
        # The server sends scroll as {direction, amount} with no x/y; honor the
        # real pixel ``amount`` and anchor sensibly (center, or the element for
        # scroll_at) instead of swiping from (0,0).
        info = self.device_info()
        raw = params.get("amount")
        pixels = int(raw) if raw is not None and raw != "" else 0
        if (
            action_type == "scroll_at"
            and params.get("x") is not None
            and params.get("y") is not None
        ):
            cx, cy = float(params["x"]), float(params["y"])
        else:
            cx, cy = info.width / 2.0, info.height / 2.0
        self._swipe(cx, cy, str(params.get("direction", "down")), pixels, info)

    # Pixels of intended travel per mouse-wheel notch (WHEEL_DELTA) on Windows.
    # There is no exact pixel<->notch mapping (one notch is ~3 lines by default,
    # but apps vary), so this is an approximate, deliberately generous ratio:
    # an ``amount`` of 500 becomes ~5 notches instead of the single-notch crawl
    # a left-button drag produced.
    _WIN_PIXELS_PER_NOTCH = 100

    def _win_wheel(self, cx: float, cy: float, direction: str, pixels: int) -> None:
        """Scroll a Windows desktop with the mouse wheel (vertical only).

        airtest's ``swipe`` is a left-button DRAG, which selects content rather
        than scrolling it; pywinauto's ``mouse.scroll`` sends a real wheel event.
        ``wheel_dist`` is a notch count: positive scrolls up, negative down.
        """
        dev = self._device
        notches = max(1, round(pixels / self._WIN_PIXELS_PER_NOTCH))
        wheel = notches if direction == "up" else -notches
        # mouse.scroll() anchors at SCREEN coords and sends the wheel to the
        # control under the cursor, so convert window->screen exactly as
        # touch()/swipe() do (_action_pos + _fix_op_pos).
        pos = dev._fix_op_pos(dev._action_pos((int(cx), int(cy))))
        dev.mouse.scroll((int(pos[0]), int(pos[1])), wheel)

    def _swipe(
        self, cx: float, cy: float, direction: str, pixels: int, info: DeviceInfo
    ) -> None:
        w, h = info.width, info.height
        span = h if direction in ("up", "down") else w
        if pixels <= 0:
            pixels = int(span * 0.6)
        # Windows scrolls with the wheel, not a drag. Vertical only — horizontal
        # wheel isn't widely supported, so left/right fall through to the drag.
        if self._platform == "windows" and direction in ("up", "down"):
            try:
                self._win_wheel(cx, cy, direction, pixels)
                return
            except Exception:
                pass  # missing internals / unsupported: fall back to a drag
        pixels = min(pixels, int(span * 0.7))  # keep the whole gesture on-screen

        if direction == "down":
            ex, ey = cx, cy - pixels
        elif direction == "up":
            ex, ey = cx, cy + pixels
        elif direction == "right":
            ex, ey = cx - pixels, cy
        elif direction == "left":
            ex, ey = cx + pixels, cy
        else:
            return

        def clamp(v: float, lo: float, hi: float) -> float:
            return max(lo, min(hi, v))

        self.drag(cx, cy, clamp(ex, w * 0.05, w * 0.95), clamp(ey, h * 0.05, h * 0.95))

    def go_back(self) -> None:
        if self._platform == "android":
            self._device.keyevent("BACK")
        else:
            raise NotImplementedError(
                f"go_back is not supported on airtest {self._platform or 'device'}"
            )

    def device_info(self) -> DeviceInfo:
        # Prefer the last screenshot's dimensions so the reported size matches
        # the image the model sees (snapshot honors orientation/rotation, which
        # get_current_resolution may disagree with in landscape).
        if self._last_size is not None:
            width, height = self._last_size
        else:
            w, h = self._device.get_current_resolution()
            width, height = int(w), int(h)
        platform = self._platform
        mapped = {"android": "android", "ios": "ios", "windows": "desktop"}.get(
            platform, platform or "android"
        )
        return DeviceInfo(platform=mapped, width=width, height=height)

    def window_info(self) -> dict[str, Any] | None:
        # Only the Windows backend is bound to a concrete OS window; Android/iOS
        # have no host window to follow (the recorder records the host screen).
        # Best-effort: the device may not be connected yet, get_title() requires
        # a connected app (it's @require_app), and handle may be None when the
        # session targets the whole desktop rather than one window.
        if self._platform != "windows":
            return None
        dev = self._device
        hwnd = getattr(dev, "handle", None)
        title: str | None = None
        try:
            titles = dev.get_title()  # airtest returns a list[str] of window texts
            if titles:
                title = titles[0]
        except Exception:
            title = None
        if not title and hwnd is None:
            return None
        return {"title": title, "hwnd": int(hwnd) if hwnd is not None else None}

    def _dispatch(self, action_type: str, params: dict[str, Any]) -> None:
        if action_type in ("scroll", "scroll_at"):
            self._scroll_action(action_type, params or {})
        else:
            super()._dispatch(action_type, params)
