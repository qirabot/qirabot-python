"""Bolt-on AI to Appium: template for testing your own Android app.

Replace app_package and app_activity with your own app, then remove the skip.

Run:
    pytest examples/appium/test_android_app.py
"""

import pytest
import os
from appium import webdriver
from appium.options.android import UiAutomator2Options
from qirabot import Qirabot

pytestmark = pytest.mark.skip(reason="Template: replace with your app")

options = UiAutomator2Options()
options.platform_name = "Android"
options.device_name = os.environ.get("ANDROID_DEVICE", "emulator-5554")
options.app_package = "com.example.myapp"        # <-- Change this
options.app_activity = ".MainActivity"            # <-- Change this

appium_url = os.environ.get("APPIUM_URL", "http://localhost:4723")
driver = webdriver.Remote(appium_url, options=options)

# bind(driver) once so AI calls drop the repeated first argument.
bot = Qirabot(task_name="test-my-app", screenshot_dir="./screenshots").bind(driver)


def test_login():
    # Your existing Appium code (native driver calls are unchanged)
    driver.find_element("id", "com.example.myapp:id/email").send_keys("user@example.com")
    driver.find_element("id", "com.example.myapp:id/password").send_keys("password123")
    driver.find_element("id", "com.example.myapp:id/login_btn").click()

    # Bolt-on: AI verifies the result
    assert bot.verify("Home screen is displayed")


def test_navigate_tabs():
    # Bolt-on: AI handles bottom nav — no need to know exact element IDs
    bot.click("Second tab in bottom navigation")
    title = bot.extract("What is the page title?")
    assert title
