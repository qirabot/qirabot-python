"""Bolt-on AI to Airtest: drive an Android app with natural language.

Airtest connects to the device itself (no Appium server needed). Qirabot then
adds AI on top, so you describe elements in plain words instead of capturing
brittle Template screenshots — and your native Airtest calls (touch / swipe /
Template) keep working alongside.

Run (connect an emulator or device via adb first):
    export QIRA_API_KEY="qk_..."
    pytest examples/airtest/test_android_app.py

Environment variables:
    export AIRTEST_DEVICE="Android:///"          # default; any connect_device URI
"""

import os

from airtest.core.api import G, connect_device, start_app, stop_app

from qirabot import Qirabot

APP = "com.android.settings"

connect_device(os.environ.get("AIRTEST_DEVICE", "Android:///"))
start_app(APP)  # open the app under test

# bind(G) once: G resolves the *current* Airtest device lazily, so calls below
# drop the repeated first argument and automatically follow set_current() if you
# switch devices. Your original Airtest style (touch(), Template, ...) still works.
bot = Qirabot(task_name="airtest-android").bind(G)


def teardown_module(module):
    # Close the app after the tests in this module finish.
    stop_app(APP)


def test_open_display():
    # AI finds "Display" regardless of Android version / OEM skin.
    bot.click("Display option")
    assert bot.verify("Display settings page is shown")


def test_search_settings():
    bot.click("Search icon")
    bot.type_text("Search input", "Bluetooth", press_enter=True)
    assert bot.verify("Bluetooth results are shown")


def test_toggle_dark_mode():
    result = bot.ai("Go to Display settings, toggle dark mode on", max_steps=8)
    assert result.success
