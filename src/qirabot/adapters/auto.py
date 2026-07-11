"""Auto-detect adapter for a given target object."""

from __future__ import annotations

import logging
from typing import Any

from qirabot.adapters.adb_adapter import AdbAdapter
from qirabot.adapters.appium_adapter import AppiumAdapter
from qirabot.adapters.base import DeviceAdapter
from qirabot.adapters.playwright_adapter import PlaywrightAdapter
from qirabot.adapters.pyautogui_adapter import PyAutoGuiAdapter
from qirabot.adapters.selenium_adapter import SeleniumAdapter
from qirabot.adapters.wda_adapter import WdaAdapter
from qirabot.adapters.windows_adapter import WindowsAdapter

logger = logging.getLogger("qirabot")

_ADAPTER_CLASSES: list[type[DeviceAdapter]] = [
    PlaywrightAdapter,
    AppiumAdapter,
    SeleniumAdapter,
    AdbAdapter,
    WdaAdapter,
    WindowsAdapter,
    PyAutoGuiAdapter,
]


def _is_airtest_target(target: Any) -> bool:
    """Tombstone check: recognize the airtest targets 1.x accepted, by module
    name strings only (zero imports — airtest is no longer a dependency)."""
    if getattr(target, "__name__", "") == "airtest.core.api":
        return True
    if getattr(target, "__name__", "") == "G" and str(
        getattr(target, "__module__", "")
    ).startswith("airtest."):
        return True
    return type(target).__module__.startswith("airtest.")


def detect(target: Any) -> DeviceAdapter:
    """Detect the appropriate adapter for a target object."""
    for cls in _ADAPTER_CLASSES:
        if cls.accepts(target):
            return cls(target)
    if _is_airtest_target(target):
        raise TypeError(
            "airtest support was removed in qirabot 2.0. Migrate the target: "
            "Android -> qirabot.AdbDevice (direct adb, zero dependencies), "
            "Windows -> qirabot.Window(hwnd=/title_re=), "
            "iOS -> qirabot.WdaClient(wda_url) — or pin qirabot<2.0 to stay "
            "on airtest. See the 2.0 migration guide in the README."
        )
    raise TypeError(
        f"Unsupported target type: {type(target).__name__}. "
        f"Supported: playwright Page, appium WebDriver, selenium WebDriver, "
        f"qirabot.AdbDevice, qirabot.WdaClient, qirabot.Window, pyautogui module"
    )
