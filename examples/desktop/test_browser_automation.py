"""Bolt-on AI to pyautogui: automate browser from OS level.

Use this when Playwright/Selenium can't work (anti-bot sites, desktop apps).

Run:
    pytest examples/desktop/test_browser_automation.py
"""

import pyautogui
from qirabot import Qirabot

# bind(pyautogui) once so calls below drop the repeated first argument.
bot = Qirabot(task_name="test-desktop-browser").bind(pyautogui)


def test_open_browser():
    bot.click("Chrome icon in the taskbar")
    bot.wait_for("A browser window is visible", timeout=10.0)
    assert bot.verify("A browser window is open")


def test_navigate_and_verify():
    bot.click("Address bar")
    bot.type_text("Address bar", "https://example.com")
    pyautogui.press("enter")
    bot.wait_for("Example Domain page loaded", timeout=10.0)
    assert bot.verify("Page shows 'Example Domain'")


def test_screenshot():
    path = bot.screenshot()
    assert path is not None
    assert path.stat().st_size > 1000
