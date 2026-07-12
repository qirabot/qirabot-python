---
title: Android Automation Without Appium — Direct over adb
description: Automate real Android devices and emulators with AI vision, no Appium server and nothing installed on the device. Python SDK and CLI over plain adb, with Chinese/emoji typing and screen recording.
---

# Android — Direct over adb

Qirabot's built-in Android backend needs **no Appium server, no framework,
and nothing installed on the device for input**: it shells out to adb
(screenshot via `screencap`, input via `input tap/swipe/keyevent`). If
`adb devices` sees it, Qirabot can drive it — real device or emulator.

Because element location is AI vision on the screenshot, there are no
UiAutomator selectors and no accessibility-tree dependency: native apps,
WebViews, Flutter, React Native, and games all look the same to it.

```python
from qirabot import AdbDevice, Qirabot

device = AdbDevice()                 # or AdbDevice(serial="emulator-5554")
bot = Qirabot().bind(device)

bot.click("Login button")            # AI-located — no template images
result = bot.ai("Open Settings and turn on dark mode")
print(f"Success: {result.success}")
bot.close()
```

The core package is enough — no extras:

```bash
uv tool install qirabot
qirabot android "Open settings and turn on airplane mode"
qirabot android "..." -d emulator-5554 --app-package com.android.settings
```

## Non-ASCII typing (Chinese, emoji)

Typing beyond ASCII works through the bundled ADBKeyboard IME — installed on
demand and switched back afterwards. `bot.type_text(...)` with Chinese or
emoji just works.

## Screen recording

Record the **device** screen (not the host) into the run report:

```python
bot = Qirabot(record_device=True)   # or QIRA_RECORD_DEVICE=1
bot.ai(device, "open settings")
bot.close()                         # pulls the video into report_dir/recording.mp4
```

Under the hood it's `adb screenrecord`; runs longer than screenrecord's
3-minute cap are merged with ffmpeg. From the CLI: `qirabot android "..." --record`.

## Through Appium instead

Have an existing Appium setup or a cloud device farm? The same API drives an
Appium driver — install `qirabot[appium]` and pass the driver:

```python
from appium import webdriver
from appium.options.android import UiAutomator2Options
from qirabot import Qirabot

options = UiAutomator2Options()
options.platform_name = "Android"
options.device_name = "emulator-5554"
driver = webdriver.Remote("http://localhost:4723", options=options)
bot = Qirabot().bind(driver)

result = bot.ai("Open Display settings and change font size to Large")
bot.close()
driver.quit()
```

On the CLI, passing `--appium-url` selects the Appium engine:
`qirabot android "..." --appium-url http://localhost:4723`.

## Platform notes

- `press_key("Back")` / `"Home"` / `"Menu"` map to adb keyevents; `go_back`
  sends `keyevent BACK`.
- `long_press` is available (touch platforms); `hover` is a no-op,
  `right_click` degrades to a tap.
- `clear_text` over raw adb is best-effort (caret-to-end + repeated delete) —
  there is no element model on purpose.
- Coming from Airtest 1.x? `connect_device("Android:///emu-5554")` becomes
  `AdbDevice("emu-5554")` — the rest of your `bind()` code is unchanged.
