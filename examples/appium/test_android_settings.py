"""Bolt-on AI to Appium: test Android Settings.

AI shines here because element IDs differ across Android versions and OEMs.

Run:
    pytest examples/appium/test_android_settings.py
"""

import os
import pytest
from appium import webdriver
from appium.options.android import UiAutomator2Options
from qirabot import Qirabot


@pytest.fixture(scope="session")
def driver():
    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.device_name = os.environ.get("ANDROID_DEVICE", "emulator-5554")
    options.app_package = "com.android.settings"
    options.app_activity = ".Settings"

    appium_url = os.environ.get("APPIUM_URL", "http://localhost:4723")
    driver = webdriver.Remote(appium_url, options=options)
    yield driver
    driver.quit()


@pytest.fixture(scope="session")
def bot(driver):
    # bind(driver) once: the Appium driver is the single, stable target for the
    # whole session, so tests drop the repeated first argument. The with-block
    # closes the Qirabot task after the last test.
    with Qirabot(task_name="test-android-settings").bind(driver) as bot:
        yield bot


def test_open_display(bot):
    # Bolt-on: AI finds "Display" regardless of Android version
    bot.click("Display option")
    assert bot.verify("Display settings page is shown")


def test_search_settings(bot):
    bot.click("Search icon")
    bot.type_text("Search input", "Bluetooth", press_enter=True)
    assert bot.verify("Bluetooth results are shown")


def test_toggle_dark_mode(bot):
    result = bot.ai("Go to Display settings, toggle dark mode on", max_steps=8)
    assert result.success


def test_device_info(bot):
    result = bot.ai("Go to About Phone, extract Android version", max_steps=8)
    assert result.success
    assert result.output
