"""Qirabot - AI automation bolt-on for any framework."""

from importlib.metadata import PackageNotFoundError, version

from qirabot._applaunch import launch_app
from qirabot.adapters.base import DeviceAdapter, DeviceInfo, ScreenshotConfig
from qirabot.client import Qirabot, RunResult, StepResult
from qirabot.exceptions import (
    ActionError,
    AuthenticationError,
    InsufficientBalanceError,
    MissingDependencyError,
    QirabotConnectionError,
    QirabotError,
    QirabotTimeoutError,
    RateLimitError,
)
from qirabot.recording import ScreenRecorder, record

try:
    __version__ = version("qirabot")
except PackageNotFoundError:  # not installed (e.g. running from a source tree)
    __version__ = "0.0.0+unknown"

__all__ = [
    "__version__",
    "ActionError",
    "AuthenticationError",
    "DeviceAdapter",
    "DeviceInfo",
    "ScreenshotConfig",
    "InsufficientBalanceError",
    "MissingDependencyError",
    "Qirabot",
    "QirabotConnectionError",
    "QirabotError",
    "QirabotTimeoutError",
    "RateLimitError",
    "RunResult",
    "ScreenRecorder",
    "StepResult",
    "launch_app",
    "record",
]
