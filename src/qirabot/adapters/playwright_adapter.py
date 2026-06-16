"""Playwright Page adapter."""

from __future__ import annotations

import logging
from typing import Any

from qirabot.adapters.base import DeviceAdapter, DeviceInfo, ScreenshotConfig

logger = logging.getLogger("qirabot")

_NEW_TAB_ACTIONS = frozenset({"click", "double_click", "type_text", "press_key"})

_KEY_ALIASES = {"ctrl": "Control", "alt": "Alt", "cmd": "Meta", "meta": "Meta", "shift": "Shift"}


def _normalize_key(key: str) -> str:
    parts = key.split("+")
    return "+".join(_KEY_ALIASES.get(p.lower(), p) for p in parts)


class PlaywrightAdapter(DeviceAdapter):
    """Adapter for playwright.sync_api.Page."""

    def __init__(self, page: Any) -> None:
        self._page = page
        self._new_page: Any | None = None
        # Keep the context we hooked and the exact handler object so close()
        # can unhook it. Re-deriving self._page.context later may yield a
        # different (or closed) context after tab switches.
        self._context = page.context
        self._context.on("page", self._on_page)

    def _on_page(self, page: Any) -> None:
        self._new_page = page

    def close(self) -> None:
        # Remove the "page" listener we registered in __init__; without this it
        # outlives the adapter and accumulates on the (longer-lived) context.
        try:
            self._context.remove_listener("page", self._on_page)
        except Exception:
            pass

    @classmethod
    def accepts(cls, target: Any) -> bool:
        t = type(target)
        return t.__module__.startswith("playwright.") and t.__name__ == "Page"

    def _switch_if_new_tab(self) -> None:
        if self._new_page is None:
            try:
                self._page.context.wait_for_event("page", timeout=1000)
            except Exception:
                return
        if self._new_page is not None:
            new_page = self._new_page
            self._new_page = None
            new_page.wait_for_load_state()
            self._page = new_page
            logger.info("switched to new tab: %s", self._page.url)

    def _switch_if_tab_closed(self) -> None:
        if not self._page.is_closed():
            return
        pages = self._page.context.pages
        if pages:
            self._page = pages[-1]
            logger.info("switched to previous tab: %s", self._page.url)

    def execute(self, action_type: str, params: dict[str, Any]) -> None:
        self._new_page = None
        super().execute(action_type, params)
        if action_type in _NEW_TAB_ACTIONS:
            self._switch_if_new_tab()
        self._switch_if_tab_closed()

    @property
    def current_target(self) -> Any:
        return self._page

    def screenshot(self, config: ScreenshotConfig | None = None) -> bytes:
        cfg = config or ScreenshotConfig()
        try:
            self._page.wait_for_load_state("networkidle", timeout=1000)
        except Exception:
            pass
        kwargs: dict[str, Any] = {"type": cfg.format}
        if cfg.format == "jpeg":
            kwargs["quality"] = cfg.quality
        return self._page.screenshot(**kwargs)  # type: ignore[no-any-return]

    def click(self, x: float, y: float) -> None:
        self._page.mouse.click(x, y)

    def double_click(self, x: float, y: float) -> None:
        self._page.mouse.dblclick(x, y)

    def right_click(self, x: float, y: float) -> None:
        self._page.mouse.click(x, y, button="right")

    def hover(self, x: float, y: float) -> None:
        self._page.mouse.move(x, y)

    def type_text(self, x: float, y: float, text: str) -> None:
        self._page.mouse.click(x, y)
        self._page.keyboard.type(text)

    def clear_text(self, x: float, y: float) -> None:
        self._page.mouse.click(x, y, click_count=3)
        self._page.keyboard.press("Backspace")

    _BROWSER_SHORTCUTS: dict[str, str] = {
        "control+w": "close",
        "meta+w": "close",
        "control+r": "reload",
        "meta+r": "reload",
        "f5": "reload",
    }

    def press_key(self, key: str) -> None:
        normalized = _normalize_key(key)
        browser_action = self._BROWSER_SHORTCUTS.get(normalized.lower())
        if browser_action == "close":
            self._page.close()
        elif browser_action == "reload":
            self._page.reload()
        else:
            self._page.keyboard.press(normalized)

    def navigate(self, url: str) -> None:
        self._page.goto(url, wait_until="domcontentloaded")

    def go_back(self) -> None:
        # Try history back first. A link opened in a NEW tab has no back history,
        # so go_back is a no-op there (the URL stays put). In that case, when
        # another tab exists, "back" means closing this tab and returning to the
        # one we came from. SPA route-backs change the URL, so they're correctly
        # treated as a real back and the tab is kept.
        before = self._page.url
        self._page.go_back(wait_until="domcontentloaded")
        self._switch_if_tab_closed()
        if self._page.url == before and len(self._page.context.pages) > 1:
            self.close_tab()

    def close_tab(self) -> None:
        self._page.close()
        self._switch_if_tab_closed()

    def drag(self, from_x: float, from_y: float, to_x: float, to_y: float) -> None:
        # A single move from source to target often fails to fire HTML5
        # dragstart/dragover (native DnD and sortable libs need the pointer to
        # travel). Nudge first to start the drag, then move in steps so the
        # intermediate dragover events land on the target.
        self._page.mouse.move(from_x, from_y)
        self._page.mouse.down()
        self._page.mouse.move(
            (from_x + to_x) / 2, (from_y + to_y) / 2, steps=5
        )
        self._page.mouse.move(to_x, to_y, steps=5)
        self._page.mouse.up()

    def scroll(self, x: float, y: float, direction: str, distance: int) -> None:
        delta_map = {"up": -1, "down": 1, "left": -1, "right": 1}
        delta = delta_map.get(direction, 1) * distance * 100
        if direction in ("up", "down"):
            self._page.mouse.wheel(0, delta)
        else:
            self._page.mouse.wheel(delta, 0)
        self._page.wait_for_timeout(300)

    def device_info(self) -> DeviceInfo:
        vp = self._page.viewport_size or {"width": 1280, "height": 720}
        return DeviceInfo(
            platform="browser",
            width=vp["width"],
            height=vp["height"],
        )
