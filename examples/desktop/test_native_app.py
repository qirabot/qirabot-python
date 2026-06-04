"""Bolt-on AI to pyautogui: test macOS Calculator.

Replace Calculator with your own desktop app.

Run:
    pytest examples/desktop/test_native_app.py
"""

import sys
import pytest
import pyautogui
from qirabot import Qirabot

if sys.platform != "darwin":
    pytest.skip("macOS only", allow_module_level=True)

bot = Qirabot(task_name="test-calculator", screenshot_dir="./screenshots")

# Open Calculator before tests. bot.launch_app is cross-platform: on Windows use
# "calc", and it handles the launch + a short wait for the window to appear.
bot.launch_app("Calculator", wait=2)


def test_basic_calculation():
    result = bot.ai(pyautogui, "Type 42 + 58 = in Calculator, tell me the result", max_steps=8)
    assert result.success
    assert "100" in result.output


def test_extract_display():
    value = bot.extract(pyautogui, "What number is shown in the Calculator?")
    assert value
