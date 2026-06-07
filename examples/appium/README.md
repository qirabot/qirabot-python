# Appium + Qirabot

Use Qirabot as a bolt-on AI layer on top of your existing Appium mobile tests.

AI is especially useful on mobile — element IDs change across Android versions, OEMs, and iOS updates.

## Install

```bash
pip install qirabot Appium-Python-Client pytest
```

## Start Appium server

**Android:**

```bash
npx appium driver install uiautomator2
npx appium
```

**iOS:**

```bash
npx appium driver install xcuitest
npx appium
```

## Start device

- Android: start an emulator or connect a device via USB
- iOS: start a simulator or connect a device

## Run

```bash
# Android
pytest examples/appium/test_android_settings.py

# iOS
pytest examples/appium/test_ios_settings.py
```

Environment variables:

```bash
export APPIUM_URL=http://localhost:4723      # default
export ANDROID_DEVICE=emulator-5554          # default
export IOS_DEVICE="iPhone 16"                # default
```

## How it works

```python
from appium import webdriver
from appium.options.android import UiAutomator2Options
from qirabot import Qirabot

options = UiAutomator2Options()
options.platform_name = "Android"
options.device_name = "emulator-5554"
options.app_package = "com.example.myapp"
options.app_activity = ".MainActivity"

driver = webdriver.Remote("http://localhost:4723", options=options)
bot = Qirabot(task_name="my-test").bind(driver)   # bind once; driver is stable

def test_login():
    # Your existing Appium code (native driver calls unchanged)
    driver.find_element("id", "com.example.myapp:id/login_btn").click()

    # Bolt-on: AI verifies — works on any Android version
    assert bot.verify("Home screen is displayed")

    # Bolt-on: AI navigates when IDs are unreliable
    result = bot.ai("Go to Settings and enable notifications", max_steps=8)
    assert result.success
```

## Examples

Bolt-on to your existing tests (run with `pytest`):

- [test_android_settings.py](test_android_settings.py) — Android Settings: display, search, dark mode
- [test_ios_settings.py](test_ios_settings.py) — iOS Settings: Wi-Fi, airplane mode, device info
- [test_android_app.py](test_android_app.py) — Template: replace with your own app

Standalone RPA — drive the phone to finish a task (run with `python`):

- [mobile_rpa.py](mobile_rpa.py) — hand a whole task to `bot.ai()`, no pytest
