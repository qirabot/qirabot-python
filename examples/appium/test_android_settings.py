"""Bolt-on AI to Appium: test Android Settings.

AI shines here because element IDs differ across Android versions and OEMs.

Run:
    pytest examples/appium/test_android_settings.py
"""

import os
from appium import webdriver
from appium.options.android import UiAutomator2Options
from qirabot import Qirabot

bot = Qirabot(task_name="test-android-settings", screenshot_dir="./screenshots")

options = UiAutomator2Options()
options.platform_name = "Android"
options.device_name = os.environ.get("ANDROID_DEVICE", "emulator-5554")
options.app_package = "com.android.settings"
options.app_activity = ".Settings"

appium_url = os.environ.get("APPIUM_URL", "http://localhost:4723")
driver = webdriver.Remote(appium_url, options=options)


def test_open_display():
    # Bolt-on: AI finds "Display" regardless of Android version
    bot.click(driver, "Display option")
    assert bot.verify(driver, "Display settings page is shown")


def test_search_settings():
    bot.click(driver, "Search icon")
    bot.type_text(driver, "Search input", "Bluetooth", press_enter=True)
    assert bot.verify(driver, "Bluetooth results are shown")


def test_toggle_dark_mode():
    result = bot.ai(driver, "Go to Display settings, toggle dark mode on", max_steps=8)
    assert result.success


def test_device_info():
    result = bot.ai(driver, "Go to About Phone, extract Android version", max_steps=8)
    assert result.success
    assert result.output
