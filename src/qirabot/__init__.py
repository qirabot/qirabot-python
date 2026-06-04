"""Qirabot - AI automation bolt-on for any framework."""

from qirabot._applaunch import launch_app
from qirabot.adapters.base import DeviceAdapter, DeviceInfo, ScreenshotConfig
from qirabot.client import Qirabot, RunResult, StepResult
from qirabot.exceptions import (
    ActionError,
    AuthenticationError,
    InsufficientBalanceError,
    QirabotError,
    QirabotTimeoutError,
)

__all__ = [
    "ActionError",
    "AuthenticationError",
    "DeviceAdapter",
    "DeviceInfo",
    "ScreenshotConfig",
    "InsufficientBalanceError",
    "Qirabot",
    "QirabotError",
    "QirabotTimeoutError",
    "RunResult",
    "StepResult",
    "launch_app",
]
