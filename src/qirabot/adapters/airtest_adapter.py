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
from typing import Any

from qirabot.adapters.base import DeviceAdapter, DeviceInfo, ScreenshotConfig, split_combo


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
        img = cv2_2_pil(self._device.snapshot())
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
        return img.transpose(Image.ROTATE_270 if ori == 1 else Image.ROTATE_90)

    def click(self, x: float, y: float) -> None:
        self._device.touch((int(x), int(y)))

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

    def type_text(self, x: float, y: float, text: str) -> None:
        self._device.touch((int(x), int(y)))
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
            for _ in range(64):
                dev.keyevent("KEYCODE_DEL")
        else:
            super().clear_text(x, y)

    # Windows keyevent() forwards to pywinauto keyboard.SendKeys() (verified in
    # airtest/core/win/win.py), whose syntax is: ^ = ctrl, % = alt, + = shift,
    # and named keys in braces ({ENTER}, {TAB}, ...). A bare "ENTER" there would
    # type the letters E-N-T-E-R, so single special keys must be braced too.
    _WIN_MODS = {"ctrl": "^", "control": "^", "alt": "%", "option": "%", "shift": "+"}
    _WIN_KEYS = {
        "enter": "{ENTER}", "return": "{ENTER}", "tab": "{TAB}", "escape": "{ESC}",
        "esc": "{ESC}", "backspace": "{BACKSPACE}", "delete": "{DELETE}", "del": "{DELETE}",
        "space": "{SPACE}", "arrowup": "{UP}", "arrowdown": "{DOWN}",
        "arrowleft": "{LEFT}", "arrowright": "{RIGHT}", "pageup": "{PGUP}",
        "pagedown": "{PGDN}", "home": "{HOME}", "end": "{END}",
    }

    def press_key(self, key: str) -> None:
        mods, base = split_combo(key)
        # Windows speaks pywinauto SendKeys syntax for BOTH single keys and
        # combos. Android/iOS use adb-style keycode names and have no ctrl-style
        # combos (the server only sends single keycodes there).
        if self._platform == "windows":
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

    def _swipe(
        self, cx: float, cy: float, direction: str, pixels: int, info: DeviceInfo
    ) -> None:
        w, h = info.width, info.height
        span = h if direction in ("up", "down") else w
        if pixels <= 0:
            pixels = int(span * 0.6)
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

    def _dispatch(self, action_type: str, params: dict[str, Any]) -> None:
        if action_type in ("scroll", "scroll_at"):
            self._scroll_action(action_type, params or {})
        else:
            super()._dispatch(action_type, params)
