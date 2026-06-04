"""Bolt-on AI to pyautogui: automate browser from OS level.

Use this when Playwright/Selenium can't work (anti-bot sites, desktop apps).

Run:
    pytest examples/desktop/test_browser_automation.py
"""

import pyautogui
from qirabot import Qirabot

bot = Qirabot(task_name="test-desktop-browser", screenshot_dir="./screenshots")


def test_open_browser():
    bot.click(pyautogui, "Chrome icon in the taskbar")
    bot.wait_for(pyautogui, "A browser window is visible", timeout=10.0)
    assert bot.verify(pyautogui, "A browser window is open")


def test_navigate_and_verify():
    bot.click(pyautogui, "Address bar")
    bot.type_text(pyautogui, "Address bar", "https://example.com")
    pyautogui.press("enter")
    bot.wait_for(pyautogui, "Example Domain page loaded", timeout=10.0)
    assert bot.verify(pyautogui, "Page shows 'Example Domain'")


def test_screenshot():
    path = bot.screenshot(pyautogui)
    assert path is not None
    assert path.stat().st_size > 1000
