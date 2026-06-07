"""Base adapter interface and device info."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ScreenshotConfig:
    """Screenshot format and quality settings."""

    format: str = "jpeg"
    quality: int = 80
    annotate: bool = False

    # Only jpeg/png are safe across every adapter: selenium/appium encode
    # anything non-png as JPEG, so an unvalidated value (e.g. "webp") would
    # mismatch the extension/mime_type derived below. Validate once here.
    _SUPPORTED_FORMATS = ("jpeg", "png")

    def __post_init__(self) -> None:
        fmt = self.format.lower()
        if fmt == "jpg":
            fmt = "jpeg"
        if fmt not in self._SUPPORTED_FORMATS:
            raise ValueError(
                f"unsupported screenshot_format {self.format!r}; "
                f"expected one of: {', '.join(self._SUPPORTED_FORMATS)}"
            )
        self.format = fmt

    @property
    def mime_type(self) -> str:
        return f"image/{self.format}"

    @property
    def extension(self) -> str:
        return "jpg" if self.format == "jpeg" else self.format


@dataclass
class DeviceInfo:
    """Device metadata sent with each AI request.

    Deliberately minimal: only what the server consumes (platform) plus the
    screen dimensions. We do not collect host/OS fingerprinting metadata
    (hostname, os, arch, …) — it has no server-side use and the client is
    open-source, so it must not silently gather machine identifiers.
    """

    platform: str
    width: int
    height: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "width": self.width,
            "height": self.height,
        }


class DeviceAdapter(ABC):
    """Abstract adapter for any automation framework."""

    @abstractmethod
    def __init__(self, target: Any) -> None:
        """Wrap a framework target (page, driver, or module)."""
        ...

    @classmethod
    @abstractmethod
    def accepts(cls, target: Any) -> bool:
        ...

    @abstractmethod
    def screenshot(self, config: ScreenshotConfig | None = None) -> bytes:
        ...

    @abstractmethod
    def click(self, x: float, y: float) -> None:
        ...

    @abstractmethod
    def double_click(self, x: float, y: float) -> None:
        ...

    def right_click(self, x: float, y: float) -> None:
        self.click(x, y)

    def hover(self, x: float, y: float) -> None:
        pass

    @abstractmethod
    def type_text(self, x: float, y: float, text: str) -> None:
        ...

    def clear_text(self, x: float, y: float) -> None:
        self.click(x, y)
        self.press_key("ctrl+a")
        self.press_key("Backspace")

    @abstractmethod
    def press_key(self, key: str) -> None:
        ...

    @abstractmethod
    def scroll(self, x: float, y: float, direction: str, distance: int) -> None:
        ...

    def drag(self, from_x: float, from_y: float, to_x: float, to_y: float) -> None:
        raise NotImplementedError(f"{type(self).__name__} does not support drag")

    def navigate(self, url: str) -> None:
        raise NotImplementedError(f"{type(self).__name__} does not support navigate")

    def go_back(self) -> None:
        raise NotImplementedError(f"{type(self).__name__} does not support go_back")

    def close_tab(self) -> None:
        raise NotImplementedError(f"{type(self).__name__} does not support close_tab")

    @property
    def current_target(self) -> Any:
        """Return the current underlying target (may change after new-tab switches)."""
        raise NotImplementedError

    @abstractmethod
    def device_info(self) -> DeviceInfo:
        ...

    def close(self) -> None:
        """Release any resources/listeners the adapter registered.

        No-op by default; adapters that hook into their framework (e.g. the
        Playwright context's ``page`` event) override this to unhook. Called by
        ``Qirabot.close()``.
        """

    def execute(self, action_type: str, params: dict[str, Any]) -> None:
        """Dispatch an action by type."""
        x = float(params.get("x", 0))
        y = float(params.get("y", 0))

        if action_type == "click":
            self.click(x, y)
        elif action_type == "double_click":
            self.double_click(x, y)
        elif action_type == "right_click":
            self.right_click(x, y)
        elif action_type == "hover":
            self.hover(x, y)
        elif action_type == "type_text":
            if params.get("clear_before_typing"):
                self.clear_text(x, y)
            self.type_text(x, y, str(params.get("text", "")))
            if params.get("press_enter"):
                self.press_key("Enter")
        elif action_type == "clear_text":
            self.clear_text(x, y)
        elif action_type == "press_key":
            self.press_key(str(params.get("key", "")))
        elif action_type in ("scroll", "scroll_at"):
            # The server sends scroll distance as `amount` in pixels (e.g. 500);
            # direct/legacy callers may pass `distance` in scroll units
            # (~amount/100, since adapters scale distance*100 -> px). Honor
            # `amount` first so the model's requested distance isn't silently
            # dropped to the default of 3.
            raw_amount = params.get("amount")
            if raw_amount not in (None, ""):
                distance = max(1, round(int(raw_amount) / 100))
            else:
                distance = int(params.get("distance", 3))
            self.scroll(x, y, str(params.get("direction", "down")), distance)
        elif action_type == "drag":
            self.drag(
                float(params.get("start_x", 0)), float(params.get("start_y", 0)),
                float(params.get("end_x", 0)), float(params.get("end_y", 0)),
            )
        elif action_type == "navigate":
            self.navigate(str(params.get("url", "")))
        elif action_type == "go_back":
            self.go_back()
        elif action_type == "wait":
            import time
            time.sleep(int(params.get("duration", 1000)) / 1000.0)
        elif action_type in ("done", "save_note"):
            pass
        else:
            raise ValueError(f"Unknown action type: {action_type}")
