---
title: iOS Automation Without Appium — Direct via WebDriverAgent
description: Automate real iPhones with AI vision by talking HTTP straight to WebDriverAgent — no Appium server, no extra packages. Setup with Xcode and iproxy, device screen recording via MJPEG.
---

# iOS — Direct via WebDriverAgent

Most iOS automation stacks put an Appium server between you and the phone.
Qirabot's built-in WDA client skips it: it talks **HTTP directly to a
WebDriverAgent** already running on the device. No Appium, no node, no extra
Python packages — the core install is enough.

Element location is AI vision on the screenshot, so there are no XCUITest
element queries to maintain, and apps that resist accessibility inspection
(games, custom-rendered UIs) work the same as native ones.

```python
from qirabot import Qirabot, WdaClient

client = WdaClient("http://127.0.0.1:8100")
client.app_launch("com.apple.Preferences")
bot = Qirabot().bind(client)

result = bot.ai("Open General > About and report the iOS version")
print(f"Success: {result.success}")
bot.close()
```

From the CLI:

```bash
qirabot ios "Send hi to Alice on WeChat" --bundle-id com.tencent.xin
```

## Real-device setup (3 steps)

1. **Run WebDriverAgent on the phone** and keep it running — in Xcode, run
   the `WebDriverAgentRunner` scheme against the device with your own signing
   team (or `xcodebuild ... -destination 'id=<udid>' -allowProvisioningUpdates test`).
2. **Forward the port over USB:** `iproxy 8100 8100` (from
   `libimobiledevice`). Sanity check: `curl http://127.0.0.1:8100/status`
   returns JSON.
3. **Run your task** — the default `--wda-url` (`http://127.0.0.1:8100`) now
   reaches the phone.

The device is selected by `--wda-url`, not by name. For multiple devices, run
one `iproxy` per device on different local ports and select with `--wda-url`.

## Simulators

For simulators, use the Appium engine instead: pass `-d/--device` with a
simulator device type (a name from `xcrun simctl list devicetypes`, e.g.
`iPhone 15`) — Appium creates and boots a matching simulator. Requires
`qirabot[appium]`.

```bash
qirabot ios "..." --device "iPhone 15"
```

Note: the Appium engine currently targets simulators only (there is no
`--udid` option) — real devices go through the WDA-direct path above.

## Device screen recording

The default recorder captures the host screen, which a phone doesn't appear
on. For iOS runs, record WDA's MJPEG stream instead (port 9100; USB real
device: `iproxy 9100 9100` alongside the usual 8100 forward — needs ffmpeg on
the host):

```python
bot = Qirabot(record_mjpeg_url="http://127.0.0.1:9100")
```

From the CLI, `qirabot ios "..." --record` does this automatically and checks
the stream is reachable before starting; `--mjpeg-url` overrides the default.

## Platform notes

- iOS has no back button; `bot.go_back()` performs the universal left-edge
  swipe gesture.
- `long_press` is available; `hover` is a no-op, `right_click` degrades to a
  tap; `clear_text` is a best-effort backspace burst (no element model over
  raw WDA — by design).
- Coming from Airtest 1.x? `connect_device("iOS:///http://...:8100")` becomes
  `WdaClient("http://...:8100")`, and `dev.driver.app_launch(...)` becomes
  `client.app_launch(...)`.
