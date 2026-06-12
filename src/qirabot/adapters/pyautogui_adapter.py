"""pyautogui module adapter for desktop automation."""

from __future__ import annotations

import platform
from typing import Any

from qirabot.adapters.base import DeviceAdapter, DeviceInfo, ScreenshotConfig


class PyAutoGuiAdapter(DeviceAdapter):
    """Adapter for the pyautogui module itself (pass the module as target)."""

    def __init__(self, module: Any) -> None:
        self._pag = module
        self._scale: float | None = None

    @classmethod
    def accepts(cls, target: Any) -> bool:
        return getattr(target, "__name__", "") == "pyautogui" and hasattr(target, "screenshot")

    @property
    def current_target(self) -> Any:
        # Desktop has a single fixed target (the pyautogui module); it never
        # changes, so it is always returned as-is.
        return self._pag

    def _scale_factor(self) -> float:
        """Ratio of screenshot pixels to pyautogui's logical coordinate space.

        On macOS Retina displays ``pyautogui.screenshot()`` captures at the
        physical backing resolution (e.g. 2880x1800) while ``pyautogui.size()``
        and the mouse/click APIs operate in logical points (e.g. 1440x900). The
        AI returns coordinates in the screenshot's pixel space, so every action
        coordinate must be divided by this factor before being handed to
        pyautogui, otherwise clicks land at ``coord * scale`` (double on 2x).
        Cached after first probe; 1.0 on non-scaled displays.
        """
        if self._scale is None:
            logical = self._pag.size()
            shot = self._pag.screenshot()
            self._scale = shot.width / logical.width if logical.width else 1.0
        return self._scale

    def _to_logical(self, x: float, y: float) -> tuple[int, int]:
        s = self._scale_factor()
        return int(x / s), int(y / s)

    @staticmethod
    def _primary_modifier() -> str:
        """Platform select-all / paste modifier ('command' on macOS, else 'ctrl')."""
        return "command" if platform.system() == "Darwin" else "ctrl"

    def _paste_text(self, text: str) -> None:
        """Type text via the system clipboard.

        ``pyautogui.typewrite`` can only emit ASCII keystrokes, so any non-ASCII
        input (e.g. Chinese) must be pasted instead. pyperclip ships transitively
        with pyautogui (via mouseinfo) and is pinned in the ``desktop`` extra.
        """
        try:
            import pyperclip
        except ImportError as e:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "typing non-ASCII text requires pyperclip; install qirabot[desktop]"
            ) from e
        pyperclip.copy(text)
        self._pag.hotkey(self._primary_modifier(), "v")

    def screenshot(self, config: ScreenshotConfig | None = None) -> bytes:
        cfg = config or ScreenshotConfig()
        img = self._pag.screenshot()
        import io
        buf = io.BytesIO()
        kwargs: dict[str, Any] = {"format": cfg.format}
        if cfg.format == "jpeg":
            kwargs["quality"] = cfg.quality
            # JPEG has no alpha channel; screenshots are often RGBA (e.g. macOS).
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
        img.save(buf, **kwargs)
        return buf.getvalue()

    def click(self, x: float, y: float) -> None:
        lx, ly = self._to_logical(x, y)
        self._pag.click(lx, ly)

    def double_click(self, x: float, y: float) -> None:
        lx, ly = self._to_logical(x, y)
        self._pag.doubleClick(lx, ly)

    def right_click(self, x: float, y: float) -> None:
        lx, ly = self._to_logical(x, y)
        self._pag.rightClick(lx, ly)

    def hover(self, x: float, y: float) -> None:
        lx, ly = self._to_logical(x, y)
        self._pag.moveTo(lx, ly)

    def type_text(self, x: float, y: float, text: str) -> None:
        lx, ly = self._to_logical(x, y)
        self._pag.click(lx, ly)
        # typewrite is ASCII-only; paste anything else (Chinese, emoji, …).
        if text.isascii():
            self._pag.typewrite(text, interval=0.02)
        else:
            self._paste_text(text)

    def clear_text(self, x: float, y: float) -> None:
        lx, ly = self._to_logical(x, y)
        self._pag.click(lx, ly)
        self._pag.hotkey(self._primary_modifier(), "a")
        self._pag.press("backspace")

    def press_key(self, key: str) -> None:
        self._pag.press(key)

    def drag(self, from_x: float, from_y: float, to_x: float, to_y: float) -> None:
        lfx, lfy = self._to_logical(from_x, from_y)
        ltx, lty = self._to_logical(to_x, to_y)
        self._pag.moveTo(lfx, lfy)
        self._pag.drag(ltx - lfx, lty - lfy, duration=0.5)

    def scroll(self, x: float, y: float, direction: str, distance: int) -> None:
        # The server's plain `scroll` sends no x/y, so they arrive as 0 and the
        # scroll would anchor at the top-left corner (menu bar / non-scrollable
        # region) and do nothing. Fall back to the screen center, matching the
        # default anchor used elsewhere.
        if not x and not y:
            info = self.device_info()
            x, y = info.width / 2.0, info.height / 2.0
        lx, ly = self._to_logical(x, y)
        clicks = distance * 3
        if direction == "up":
            self._pag.scroll(clicks, x=lx, y=ly)
        elif direction == "down":
            self._pag.scroll(-clicks, x=lx, y=ly)
        elif direction == "left":
            self._pag.hscroll(-clicks, x=lx, y=ly)
        elif direction == "right":
            self._pag.hscroll(clicks, x=lx, y=ly)

    # Actions that don't change the screen (or handle their own timing), so the
    # next screenshot needs no settle delay after them.
    _NO_SETTLE = frozenset({"wait", "done", "save_note", "hover"})

    # Desktop UI (scroll inertia, window transitions) needs a generous floor; see
    # ``DeviceAdapter.settle_seconds`` for the rationale and override mechanism.
    _SETTLE_SECONDS = 1.0

    def device_info(self) -> DeviceInfo:
        # Report screenshot (physical) pixels, not pyautogui's logical points, so
        # the dimensions match the captured image and the screenshot-pixel
        # coordinate convention every adapter method consumes. Otherwise on a 2x
        # Retina display Qirabot.scroll()'s default center anchor (info.width / 2,
        # in logical points) would be divided by the scale factor a second time
        # inside _to_logical and land at a quarter position. Reuses the cached
        # scale probe; == 1.0 (unchanged) on non-scaled displays.
        s = self._scale_factor()
        size = self._pag.size()
        return DeviceInfo(
            platform="desktop",
            width=int(size.width * s),
            height=int(size.height * s),
        )
