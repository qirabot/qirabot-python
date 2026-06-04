"""Bolt-on AI to Appium: test iOS Settings.

AI handles iOS UI elements that change across iOS versions.

Run:
    pytest examples/appium/test_ios_settings.py
"""

import os
from appium import webdriver
from appium.options.ios import XCUITestOptions
from qirabot import Qirabot

bot = Qirabot(task_name="test-ios-settings", screenshot_dir="./screenshots")

options = XCUITestOptions()
options.platform_name = "iOS"
options.device_name = os.environ.get("IOS_DEVICE", "iPhone 16")
options.bundle_id = "com.apple.Preferences"

appium_url = os.environ.get("APPIUM_URL", "http://localhost:4723")
driver = webdriver.Remote(appium_url, options=options)


def test_open_wifi():
    bot.click(driver, "Wi-Fi option")
    assert bot.verify(driver, "Wi-Fi settings page is shown")


def test_search_settings():
    # Swipe down to reveal search — AI handles the gesture
    bot.click(driver, "Search field")
    bot.type_text(driver, "Search field", "Bluetooth", press_enter=True)
    assert bot.verify(driver, "Bluetooth related results are shown")


def test_toggle_airplane_mode():
    result = bot.ai(driver, "Toggle Airplane Mode on", max_steps=5)
    assert result.success
    assert bot.verify(driver, "Airplane Mode is turned on")


def test_device_info():
    result = bot.ai(
        driver,
        "Go to General > About, extract the iOS version and device name",
        max_steps=8,
    )
    assert result.success
    assert result.output
