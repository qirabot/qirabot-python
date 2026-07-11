"""Direct-WDA iOS adapter (no Appium server, no facebook-wda).

Drives a :class:`~qirabot.wda.WdaClient`. Coordinates follow the Appium-iOS
convention already used by :class:`AppiumAdapter`: ``device_info`` reports
logical points (WDA's own coordinate space), screenshots come back at physical
pixels, and ``annotation_scale`` carries the Retina ratio so report crosshairs
land where the tap happened.
"""

from __future__ import annotations

import io
import time
from typing import Any

from qirabot.adapters.base import DeviceAdapter, DeviceInfo, ScreenshotConfig, split_combo
from qirabot.wda import WdaClient

# press_key names → WDA pressButton names (the whole set WDA accepts). home is
# handled separately via the sessionless /wda/homescreen route.
_BUTTONS = {
    "volumeup": "volumeUp",
    "volume_up": "volumeUp",
    "volumedown": "volumeDown",
    "volume_down": "volumeDown",
}


class WdaAdapter(DeviceAdapter):
    """Adapter for :class:`qirabot.wda.WdaClient` targets."""

    # Actions that don't change the screen (or handle their own timing), so the
    # next screenshot needs no settle delay after them.
    _NO_SETTLE = frozenset({"wait", "done", "save_note"})

    # WDA animates gestures and returns promptly; iOS transitions are quick, so
    # a smaller floor than Android's (see DeviceAdapter.settle_seconds).
    _SETTLE_SECONDS = 0.6

    # Delay between the focusing tap and the first keystroke, so the keyboard
    # finishes appearing before characters arrive.
    _FOCUS_SETTLE = 0.3

    def __init__(self, target: Any) -> None:
        self._client: WdaClient = target
        self._size: tuple[int, int] | None = None  # logical points, cached
        self._annotation_scale: float | None = None

    @classmethod
    def accepts(cls, target: Any) -> bool:
        return isinstance(target, WdaClient)

    @property
    def current_target(self) -> Any:
        return self._client

    # ---- screen -------------------------------------------------------------

    def screenshot(self, config: ScreenshotConfig | None = None) -> bytes:
        cfg = config or ScreenshotConfig()
        png = self._client.screenshot()
        # Screenshots are physical pixels, window_size is logical points; probe
        # the ratio once (PNG header only) so report annotations can be drawn
        # at the visual tap position. Best-effort, like the Appium adapter.
        if self._annotation_scale is None:
            try:
                from PIL import Image

                with Image.open(io.BytesIO(png)) as probe:
                    logical_w = self._window_size()[0]
                    if logical_w:
                        self._annotation_scale = probe.width / logical_w
            except Exception:
                pass
        if cfg.format == "png":
            return png
        from PIL import Image

        img: Image.Image = Image.open(io.BytesIO(png))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=cfg.quality)
        return buf.getvalue()

    def annotation_scale(self) -> float:
        return self._annotation_scale if self._annotation_scale else 1.0

    def _window_size(self) -> tuple[int, int]:
        if self._size is None:
            self._size = self._client.window_size()
        return self._size

    def device_info(self) -> DeviceInfo:
        width, height = self._window_size()
        return DeviceInfo(platform="ios", width=width, height=height)

    # ---- pointer ------------------------------------------------------------

    def click(self, x: float, y: float) -> None:
        self._client.tap(int(x), int(y))

    def double_click(self, x: float, y: float) -> None:
        self._client.double_tap(int(x), int(y))

    def long_press(self, x: float, y: float, duration: float = 2.0) -> None:
        self._client.tap_hold(int(x), int(y), duration)

    def drag(self, from_x: float, from_y: float, to_x: float, to_y: float) -> None:
        self._client.swipe(
            int(from_x), int(from_y), int(to_x), int(to_y), duration=0.5
        )

    # ---- scrolling (same geometry as the other device adapters) --------------

    def scroll(self, x: float, y: float, direction: str, distance: int) -> None:
        info = self.device_info()
        cx = x or info.width / 2.0
        cy = y or info.height / 2.0
        self._swipe(cx, cy, direction, distance * 100, info)

    def _scroll_action(self, action_type: str, params: dict[str, Any]) -> None:
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

        self._client.swipe(
            int(cx),
            int(cy),
            int(clamp(ex, w * 0.05, w * 0.95)),
            int(clamp(ey, h * 0.05, h * 0.95)),
            duration=0,
        )

    def _dispatch(self, action_type: str, params: dict[str, Any]) -> None:
        if action_type in ("scroll", "scroll_at"):
            self._scroll_action(action_type, params or {})
        else:
            super()._dispatch(action_type, params)

    # ---- keys / text ---------------------------------------------------------

    def press_key(self, key: str) -> None:
        _mods, base = split_combo(key)  # iOS has no held-modifier concept
        k = base.lower()
        if k in ("enter", "return"):
            self._client.send_keys("\n")
        elif k in ("backspace", "delete", "del"):
            self._client.send_keys("\b")
        elif k == "home":
            self._client.home()
        elif k in _BUTTONS:
            self._client.press_button(_BUTTONS[k])
        elif k in ("lock", "power"):
            self._client.lock()
        else:
            raise NotImplementedError(f"iOS does not support key {key!r}")

    def go_back(self) -> None:
        # iOS has no back button; the universal gesture is a left-edge swipe.
        w, h = self._window_size()
        self._client.swipe(1, int(h * 0.5), int(w * 0.6), int(h * 0.5), duration=0)

    def type_text(self, x: float, y: float, text: str) -> None:
        self.click(x, y)
        time.sleep(self._FOCUS_SETTLE)
        self.type_focused(text)

    def type_focused(self, text: str) -> None:
        if text:
            self._client.send_keys(text)

    def clear_focused(self) -> None:
        # No element model here: a burst of backspaces is the WDA-level best
        # effort (one request — /wda/keys takes the whole list at once).
        self._client.send_keys("\b" * 64)
