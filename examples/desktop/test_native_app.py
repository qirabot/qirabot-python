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


@pytest.fixture(scope="session")
def bot():
    # bind(pyautogui) once: desktop has a single fixed target (the pyautogui
    # module), so tests drop the repeated first argument. The with-block closes
    # the Qirabot task after the last test.
    with Qirabot(task_name="test-calculator").bind(pyautogui) as bot:
        # Open Calculator before tests. launch_app works on the bound proxy and
        # is cross-platform: on Windows use "calc"; it handles the launch + a
        # short wait for the window to appear.
        bot.launch_app("Calculator", wait=2)
        yield bot


def test_basic_calculation(bot):
    result = bot.ai("Type 42 + 58 = in Calculator, tell me the result", max_steps=8)
    assert result.success
    assert "100" in result.output


def test_extract_display(bot):
    value = bot.extract("What number is shown in the Calculator?")
    assert value
