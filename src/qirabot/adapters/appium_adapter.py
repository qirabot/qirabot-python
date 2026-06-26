"""Appium WebDriver adapter for Android and iOS."""

from __future__ import annotations

import base64
import io
from typing import Any

from qirabot.adapters.base import DeviceAdapter, DeviceInfo, ScreenshotConfig


class AppiumAdapter(DeviceAdapter):
    """Adapter for appium.webdriver.webdriver.WebDriver (Android + iOS)."""

    def __init__(self, driver: Any) -> None:
        self._driver = driver
        caps = driver.capabilities or {}
        self._platform = (caps.get("platformName") or "").lower()

    @classmethod
    def accepts(cls, target: Any) -> bool:
        t = type(target)
        return t.__module__.startswith("appium.")

    @property
    def current_target(self) -> Any:
        return self._driver

    def screenshot(self, config: ScreenshotConfig | None = None) -> bytes:
        cfg = config or ScreenshotConfig()
        png_bytes = base64.b64decode(self._driver.get_screenshot_as_base64())
        if cfg.format == "png":
            return png_bytes
        from PIL import Image

        img: Image.Image = Image.open(io.BytesIO(png_bytes))
        # JPEG has no alpha channel; PNG screenshots may be RGBA.
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=cfg.quality)
        return buf.getvalue()

    def _tap(self, x: float, y: float, pause: float = 0.1) -> None:
        from selenium.webdriver.common.action_chains import ActionChains

        # add_pointer_input takes (kind, name) strings and builds the
        # PointerInput itself — passing a PointerInput object raises TypeError,
        # which ai()'s loop swallows so taps silently no-op. The pause between
        # down/up makes the tap register reliably on real devices; a longer
        # pause turns the same gesture into a long press.
        actions = ActionChains(self._driver)
        touch = actions.w3c_actions.add_pointer_input("touch", "finger")
        touch.create_pointer_move(x=int(x), y=int(y), duration=0)
        touch.create_pointer_down(button=0)
        touch.create_pause(pause)
        touch.create_pointer_up(button=0)
        actions.perform()

    def click(self, x: float, y: float) -> None:
        self._tap(x, y)

    def double_click(self, x: float, y: float) -> None:
        self._tap(x, y)
        self._tap(x, y)

    def long_press(self, x: float, y: float, duration: float = 2.0) -> None:
        # Same pointer sequence as a tap, just holding for `duration` seconds.
        self._tap(x, y, pause=duration)

    def _focused_element(self) -> Any:
        """Return the currently focused input element.

        The WebDriver object itself has no send_keys (that lives on elements),
        so typing must go through the focused element. On Android the
        focused(true) UiSelector is the most reliable — it finds the active
        field even when it's an AutoCompleteTextView / custom widget rather than
        a plain EditText. active_element is the cross-platform fallback (iOS).
        """
        if self._platform == "android":
            from appium.webdriver.common.appiumby import AppiumBy

            try:
                return self._driver.find_element(
                    AppiumBy.ANDROID_UIAUTOMATOR, "new UiSelector().focused(true)"
                )
            except Exception:
                pass
        return self._driver.switch_to.active_element

    def type_text(self, x: float, y: float, text: str) -> None:
        self._tap(x, y)
        self._focused_element().send_keys(text)

    def clear_text(self, x: float, y: float) -> None:
        self._tap(x, y)
        el = self._focused_element()
        if el:
            el.clear()

    def press_key(self, key: str) -> None:
        if self._platform == "android":
            key_map = {
                "enter": 66, "back": 4, "home": 3, "menu": 82,
                "volume_up": 24, "volume_down": 25, "power": 26,
                "tab": 61, "delete": 67, "backspace": 67,
            }
            code = key_map.get(key.lower())
            if code is not None:
                self._driver.press_keycode(code)
            else:
                self._focused_element().send_keys(key)
        else:
            # iOS：键名要转成 XCUITest 能识别的字符，否则会被当文本输入。
            # 回车需发 "\n" 触发键盘 return/搜索键（直接发 "Enter" 会输出字面文字）。
            ios_key_map = {"enter": "\n", "return": "\n", "tab": "\t"}
            self._focused_element().send_keys(ios_key_map.get(key.lower(), key))

    def drag(self, from_x: float, from_y: float, to_x: float, to_y: float) -> None:
        from selenium.webdriver.common.action_chains import ActionChains

        # See _tap: add_pointer_input wants (kind, name) strings, not a
        # PointerInput object.
        actions = ActionChains(self._driver)
        touch = actions.w3c_actions.add_pointer_input("touch", "finger")
        touch.create_pointer_move(x=int(from_x), y=int(from_y), duration=0)
        touch.create_pointer_down(button=0)
        touch.create_pause(0.5)
        touch.create_pointer_move(x=int(to_x), y=int(to_y), duration=500)
        touch.create_pointer_up(button=0)
        actions.perform()

    # Actions that don't change the screen (or handle their own timing), so the
    # next screenshot needs no settle delay after them. hover is deliberately NOT
    # here: its whole purpose is to reveal delayed UI (tooltips/submenus), so it
    # needs the settle more than most actions, not less.
    _NO_SETTLE = frozenset({"wait", "done", "save_note"})

    # Mobile transitions/animations/app launches; see
    # ``DeviceAdapter.settle_seconds`` for the rationale and override mechanism.
    _SETTLE_SECONDS = 0.6

    def _dispatch(self, action_type: str, params: dict[str, Any]) -> None:
        if action_type in ("scroll", "scroll_at"):
            self._scroll_action(action_type, params or {})
        else:
            super()._dispatch(action_type, params)

    def _scroll_action(self, action_type: str, params: dict[str, Any]) -> None:
        # The server sends scroll as {direction, amount} with no x/y, so the
        # base dispatcher (which reads x/y/distance) would swipe from (0,0) by a
        # default distance and miss the screen. Use the real pixel `amount` and a
        # sensible anchor instead.
        info = self.device_info()
        raw = params.get("amount")
        pixels = int(raw) if raw is not None and raw != "" else 0
        # scroll_at anchors on the resolved element; plain scroll on center.
        if action_type == "scroll_at" and params.get("x") is not None and params.get("y") is not None:
            cx, cy = float(params["x"]), float(params["y"])
        else:
            cx, cy = info.width / 2.0, info.height / 2.0
        self._swipe(cx, cy, str(params.get("direction", "down")), pixels, info)

    def scroll(self, x: float, y: float, direction: str, distance: int) -> None:
        # DeviceAdapter contract / direct callers. The server path goes through
        # execute() above; here `distance` keeps the legacy ×100 unit, and a
        # zero anchor falls back to screen center.
        info = self.device_info()
        cx = x or info.width / 2.0
        cy = y or info.height / 2.0
        self._swipe(cx, cy, direction, distance * 100, info)

    def _swipe(self, cx: float, cy: float, direction: str, pixels: int, info: DeviceInfo) -> None:
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

    def navigate(self, url: str) -> None:
        self._driver.get(url)

    def go_back(self) -> None:
        self._driver.back()

    def device_info(self) -> DeviceInfo:
        size = self._driver.get_window_size()
        platform = self._platform or "android"
        return DeviceInfo(
            platform=platform,
            width=size.get("width", 1080),
            height=size.get("height", 1920),
        )
