"""Qirabot - AI automation bolt-on for any framework."""

from importlib.metadata import PackageNotFoundError, version

from qirabot._applaunch import launch_app
from qirabot._dotenv import load_dotenv
from qirabot.adapters.base import DeviceAdapter, DeviceInfo, ScreenshotConfig
from qirabot.adb import AdbDevice
from qirabot.wda import WdaClient
from qirabot.windows import Window
from qirabot.client import (
    ExtractResult,
    Qirabot,
    RunResult,
    RunStatus,
    StepResult,
    VerifyResult,
)
from qirabot.exceptions import (
    ActionError,
    AuthenticationError,
    InsufficientBalanceError,
    MissingDependencyError,
    QirabotConnectionError,
    QirabotError,
    QirabotTimeoutError,
    RateLimitError,
    TaskTerminatedError,
)
from qirabot.recording import (
    AdbScreenRecorder,
    AppiumScreenRecorder,
    MjpegStreamRecorder,
    ScreenRecorder,
    record,
    window_region,
)

try:
    __version__ = version("qirabot")
except PackageNotFoundError:  # not installed (e.g. running from a source tree)
    __version__ = "0.0.0+unknown"

__all__ = [
    "__version__",
    "ActionError",
    "AdbDevice",
    "AdbScreenRecorder",
    "AppiumScreenRecorder",
    "AuthenticationError",
    "DeviceAdapter",
    "DeviceInfo",
    "ExtractResult",
    "ScreenshotConfig",
    "InsufficientBalanceError",
    "MissingDependencyError",
    "MjpegStreamRecorder",
    "Qirabot",
    "QirabotConnectionError",
    "QirabotError",
    "QirabotTimeoutError",
    "RateLimitError",
    "RunResult",
    "RunStatus",
    "ScreenRecorder",
    "StepResult",
    "TaskTerminatedError",
    "VerifyResult",
    "WdaClient",
    "Window",
    "launch_app",
    "load_dotenv",
    "record",
    "window_region",
]
