"""Bolt-on AI to Appium: test iOS Settings.

AI handles iOS UI elements that change across iOS versions.

Run:
    pytest examples/appium/test_ios_settings.py
"""

import os
from appium import webdriver
from appium.options.ios import XCUITestOptions
from qirabot import Qirabot

options = XCUITestOptions()
options.platform_name = "iOS"
options.device_name = os.environ.get("IOS_DEVICE", "iPhone 16")
options.bundle_id = "com.apple.Preferences"

appium_url = os.environ.get("APPIUM_URL", "http://localhost:4723")
driver = webdriver.Remote(appium_url, options=options)

# bind(driver) once so calls below drop the repeated first argument.
bot = Qirabot(task_name="test-ios-settings").bind(driver)


def test_open_wifi():
    bot.click("Wi-Fi option")
    assert bot.verify("Wi-Fi settings page is shown")


def test_search_settings():
    # Swipe down to reveal search — AI handles the gesture
    bot.click("Search field")
    bot.type_text("Search field", "Bluetooth", press_enter=True)
    assert bot.verify("Bluetooth related results are shown")


def test_toggle_airplane_mode():
    result = bot.ai("Toggle Airplane Mode on", max_steps=5)
    assert result.success
    assert bot.verify("Airplane Mode is turned on")


def test_device_info():
    result = bot.ai(
        "Go to General > About, extract the iOS version and device name",
        max_steps=8,
    )
    assert result.success
    assert result.output
