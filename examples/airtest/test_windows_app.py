"""Bolt-on AI to Airtest on Windows desktop.

Airtest can drive native Windows apps — a surface Appium doesn't cover and where
pyautogui has no built-in device model. Connect to the desktop, launch an app,
and let AI click by description.

Run (Windows only):
    export QIRA_API_KEY="qk_..."
    pytest examples/airtest/test_windows_app.py
"""

import sys

import pytest

from airtest.core.api import G, connect_device, keyevent

from qirabot import Qirabot

if sys.platform != "win32":
    pytest.skip("Windows only — Airtest Windows backend", allow_module_level=True)

# Connect to the whole desktop. You can also target one window, e.g.
# connect_device("Windows:///?title_re='.*Calculator.*'").
connect_device("Windows:///")
bot = Qirabot(task_name="airtest-windows").bind(G)

# Open the app. pyautogui can't, but Qirabot's launch_app shells out
# cross-platform; on the bound proxy it delegates to the underlying Qirabot.
bot.launch_app("calc", wait=2)


def teardown_module(module):
    # Close the app. Windows' stop_app() needs a PID, so close the focused
    # window with Alt+F4 (pywinauto syntax) instead.
    keyevent("%{F4}")


def test_calculation():
    result = bot.ai("Compute 42 + 58 and read the result", max_steps=10)
    assert result.success
    assert "100" in result.output


def test_extract_display():
    value = bot.extract("What number is shown in the calculator display?")
    assert value
