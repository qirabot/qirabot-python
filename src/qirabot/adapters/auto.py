"""Auto-detect adapter for a given target object."""

from __future__ import annotations

import logging
from typing import Any

from qirabot.adapters.adb_adapter import AdbAdapter
from qirabot.adapters.airtest_adapter import AirtestAdapter
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
    AirtestAdapter,
    PyAutoGuiAdapter,
]


def detect(target: Any) -> DeviceAdapter:
    """Detect the appropriate adapter for a target object."""
    for cls in _ADAPTER_CLASSES:
        if cls.accepts(target):
            return cls(target)
    raise TypeError(
        f"Unsupported target type: {type(target).__name__}. "
        f"Supported: playwright Page, appium WebDriver, selenium WebDriver, "
        f"airtest device / G / airtest.core.api module, pyautogui module"
    )
