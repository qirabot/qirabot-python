"""Device adapters for Qirabot SDK."""

from qirabot.adapters.auto import detect
from qirabot.adapters.base import DeviceAdapter, DeviceInfo

__all__ = ["DeviceAdapter", "DeviceInfo", "detect"]
