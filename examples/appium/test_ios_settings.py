"""Bolt-on AI to Appium: test iOS Settings.

AI handles iOS UI elements that change across iOS versions.

Run:
    pytest examples/appium/test_ios_settings.py
"""

import os
import pytest
from appium import webdriver
from appium.options.ios import XCUITestOptions
from qirabot import Qirabot


@pytest.fixture(scope="session")
def driver():
    options = XCUITestOptions()
    options.platform_name = "iOS"
    # deviceName alone targets a simulator; a real device needs options.udid too
    options.device_name = os.environ.get("IOS_DEVICE", "iPhone 16")
    options.bundle_id = "com.apple.Preferences"

    appium_url = os.environ.get("APPIUM_URL", "http://localhost:4723")
    driver = webdriver.Remote(appium_url, options=options)
    yield driver
    driver.quit()


@pytest.fixture(scope="session")
def bot(driver):
    # bind(driver) once so calls below drop the repeated first argument; the
    # with-block closes the Qirabot task after the last test.
    with Qirabot(task_name="test-ios-settings").bind(driver) as bot:
        yield bot


def test_open_wifi(bot):
    bot.click("Wi-Fi option")
    assert bot.verify("Wi-Fi settings page is shown")


def test_search_settings(bot):
    # Swipe down to reveal search — AI handles the gesture
    bot.click("Search field")
    bot.type_text("Search field", "Bluetooth", press_enter=True)
    assert bot.verify("Bluetooth related results are shown")


def test_toggle_airplane_mode(bot):
    result = bot.ai("Toggle Airplane Mode on", max_steps=5)
    assert result.success
    assert bot.verify("Airplane Mode is turned on")


def test_device_info(bot):
    result = bot.ai(
        "Go to General > About, extract the iOS version and device name",
        max_steps=8,
    )
    assert result.success
    assert result.output
