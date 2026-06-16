# Qirabot Python SDK

AI-powered automation SDK that bolts onto your existing browser/mobile automation framework. Let AI see the screen, click, type, extract data, and verify results — with any framework you already use.

Use it two ways: as a **Python library** (let qirabot launch a Playwright browser for you via `bot.open()`, or bolt onto a Playwright / Selenium / Appium / Airtest / pyautogui session you already drive), or inside your **pytest suite**.

## Installation

```bash
pip install qirabot
```

Requires Python 3.10+.

The core package has no automation engine of its own — install the extra for the
framework you'll drive:

```bash
pip install "qirabot[browser]"   # Playwright (needed for bot.open())
pip install "qirabot[desktop]"   # pyautogui (native desktop apps)
pip install "qirabot[appium]"    # Appium (Android / iOS)
pip install "qirabot[airtest]"   # Airtest (Android / iOS / Windows, image-based)

pip install selenium             # Selenium is not an extra — bring your own driver
```

> The `airtest` extra pulls in Airtest, which pins `numpy<2.0` and
> `opencv-contrib-python` 4.4–4.6. These have prebuilt wheels only up to
> **Python 3.12** — on Python 3.13/3.14 pip falls back to building them from
> source and fails without a C/C++ compiler (e.g. MSVC on Windows). **For the
> `airtest` extra, use Python 3.10–3.12.** Installing into an env that already
> has `numpy>=2` may also downgrade or conflict — prefer a dedicated virtualenv.

The Quick Start below uses `bot.open()`, so it needs `qirabot[browser]` plus a
one-time `playwright install chromium`. With Selenium you create the driver
yourself and pass it to qirabot — see [examples/selenium/](examples/selenium/).

## Configuration

```bash
export QIRA_API_KEY="qk_your_api_key"
```

```python
from qirabot import Qirabot

bot = Qirabot()  # reads QIRA_API_KEY from environment
```

Constructor options:

| Parameter | Env Variable | Default | Description |
|---|---|---|---|
| `api_key` | `QIRA_API_KEY` | — | API key for authentication |
| `base_url` | `QIRA_BASE_URL` | `https://app.qirabot.com` | API server URL |
| `timeout` | — | `120.0` | HTTP request timeout (seconds) |
| `model_alias` | — | `""` | Default model alias for all operations |
| `language` | — | `""` | Default response language |
| `task_name` | — | `""` | Optional name for the task (visible in dashboard) |
| `report` | — | `True` | Write an HTML run report (+ screenshots) on close |
| `report_dir` | `QIRA_REPORT_DIR` | `""` | Output root; default `./qira_runs/<date>/<time-id>/` |
| `screenshot_annotate` | — | `True` | Draw a red crosshair at click/type coordinates |
| `screenshot_format` | — | `"jpeg"` | Saved screenshot format (`"jpeg"` or `"png"`) |
| `screenshot_quality` | — | `80` | JPEG quality, 1–100 |
| `retry` | — | `1` | Retries per action on transient failures |
| `retry_delay` | — | `1.0` | Seconds between retries |
| `settle_seconds` | `QIRA_SETTLE_SECONDS` | per-platform | Fixed pause after each action so the UI repaints before the next screenshot |

### Model & language

`model_alias` selects which model backs every operation. The built-in aliases
trade cost for quality:

| Alias | Trade-off |
|---|---|
| `fast` | Cheapest, lowest latency |
| `balanced` | The default — good cost/quality balance |
| `balanced_pro` | Stronger than `balanced` |
| `high_quality` | Best quality, highest cost |

Check your dashboard for the live list your account can use, then pass the
`name` as `model_alias`; leave it empty for the default:

```python
bot = Qirabot(model_alias="high_quality")        # applies to all actions
bot.click(page, "Login", model_alias="fast")     # or override per call
```

`language` sets the language of AI responses (extracted text, reasoning). It's a
short language tag like `"zh"` or `"en"` — empty means the server default:

```python
bot = Qirabot(language="zh")                      # extract/ai answers in Chinese
text = bot.extract(page, "获取主标题", language="zh")
```

## Quick Start

This uses `bot.open()`, so install the browser extra and Chromium first:

```bash
pip install "qirabot[browser]"
playwright install chromium
```

```python
from qirabot import Qirabot

bot = Qirabot()
page = bot.open("https://google.com")

bot.type_text(page, "Search input", "SpaceX", press_enter=True)

summary = bot.extract(page, "Get the first search result title")
print(f"Result: {summary}")

bot.close()
```

## Bind a target (optional)

Every action takes the framework object (`page` / `driver` / device / module) as
its first argument: `bot.click(target, "Login")`. When you drive a **single,
stable target** for the whole session, call `bot.bind(target)` once to get a
drop-in proxy that drops the repeated first argument:

```python
bot = Qirabot().bind(driver)     # Selenium/Appium driver, pyautogui, Airtest G/device
bot.click("Login")
bot.type_text("Email", "a@b.com")
with Qirabot().bind(driver) as bot:   # works as a context manager too
    ...
```

`bind()` is recommended for **Airtest, pyautogui, Appium, Selenium**. For
**Playwright** keep the explicit form `page = bot.click(page, ...)` so new-tab
follows stay visible (a click can open a new tab; the returned page is the one
your native `page.fill(...)` calls should use). With a bound proxy, reach the
live page via `bot.current_page()`.

## Examples

Runnable examples live in [examples/](examples/), in two styles:

- **Bolt onto your existing tests (pytest)** — add AI to a suite you already
  have: [playwright/](examples/playwright/), [selenium/](examples/selenium/),
  [appium/](examples/appium/), [desktop/](examples/desktop/).
- **Standalone automation (plain scripts)** — scraping / RPA / agents, run with
  `python`: [automation/](examples/automation/).

See [examples/README.md](examples/README.md) for which to pick.

## API Reference

### Simple Actions

These actions use lightweight vision-based element location — fast and low-cost:

```python
# Click on an element by description
bot.click(page, "Login button")

# Auto-wait: poll until the element looks present (up to timeout) before
# clicking, else raise QirabotTimeoutError. Works on every framework.
# `wait` overrides the auto-derived assertion. (Also on type_text/double_click.)
bot.click(page, "Login button", timeout=15.0, interval=2.0)

# Type text into an input field
bot.type_text(page, "Email input", "user@example.com")

# Extract data from the screen
text = bot.extract(page, "Get the main heading")

# Verify a visual assertion (returns True/False, never raises)
ok = bot.verify(page, "The success message is visible")

# Wait for a condition (acts as a gate): returns when met, else raises
# QirabotTimeoutError. Use verify() for a non-raising bool check.
bot.wait_for(page, "Page has finished loading", timeout=15.0, interval=2.0)
```

`click`, `type_text`, and `double_click` return the current target (the same
kind you passed in). When an action opens a link in a **new tab**, the return
value is that new tab, so reassign it to keep operating on the active page:

```python
page = bot.click(page, "Open the first video")  # may switch to a new tab
```

### Settle delay

After every screen-changing action each adapter pauses briefly so the UI repaints
before the next screenshot — without it the model can capture a mid-animation frame
and wrongly conclude the action did nothing. The defaults are tuned per platform
(desktop `1.0`s, mobile/browser `0.6`s, Airtest `1`s; Playwright relies on its own
auto-waiting and adds none).

Override the floor globally with `settle_seconds` — useful to slow down for a laggy
remote device, or speed up a snappy local app. `0` disables it (rely on `wait_for`
/ `timeout=` polling instead, which is more precise):

```python
bot = Qirabot(settle_seconds=1.5)   # laggy environment: wait longer
bot = Qirabot(settle_seconds=0.3)   # fast local app: go quicker
bot = Qirabot(settle_seconds=0)     # disable; lean on wait_for() instead
# or, without touching code:  export QIRA_SETTLE_SECONDS=1.5
```

This is a blunt fixed delay. For "wait until X appears" prefer the auto-wait
`timeout=`/`wait_for()` polling shown above — it returns as soon as the condition
holds instead of always sleeping the full interval.

### Multi-Step AI (`bot.ai()`)

Let AI autonomously complete a complex task using the full decision engine:

```python
from qirabot import Qirabot, StepResult

bot = Qirabot()
page = bot.open("https://www.google.com")

def on_step(step: StepResult) -> None:
    status = "done" if step.finished else step.action_type
    print(f"  Step {step.step}: {status} {step.params}")

result = bot.ai(
    page,
    "Search for 'best python libraries 2026', click the first result, and extract the main content",
    max_steps=10,
    on_step=on_step,
)

print(f"Success: {result.success}")
print(f"Output: {result.output}")
bot.close()
```

### Screenshot (No AI)

Saves to `report_dir/screenshots/` and returns the saved path (or `None` when
`report=False`):

```python
path = bot.screenshot(page)
print(f"saved to {path}")
```

### Navigation, Scrolling & Keys (No AI)

Direct, non-billed actions that don't need AI element location. `go_back`,
`navigate`, `close_tab`, and `press_key` return the current page/target (may
differ after the action); `scroll` returns `None`.

```python
bot.navigate(page, "example.com")   # scheme optional; "https://" prepended
bot.go_back(page)                   # back to the previous page (smart, see below)
page = bot.close_tab(page)          # close current tab, return to previous tab
bot.scroll(page, "down", 3)         # scroll at viewport center
bot.scroll(page, "up", distance=5, x=640, y=400)  # scroll at a point
bot.press_key(page, "Enter")        # a single key
bot.press_key(page, "ctrl+c")       # a combo (join with "+")
page = bot.press_key(page, "ctrl+t")  # ctrl+t/ctrl+w switch the active tab — reassign
```

**`press_key` — what you can pass.** One name works on every backend; each maps
it to its own vocabulary.

| Category | Examples | Notes |
| --- | --- | --- |
| Single keys | `Enter` `Escape` `Tab` `Backspace` `Delete` `Space` | |
| Arrows / paging | `ArrowUp/Down/Left/Right` `PageUp` `PageDown` `Home` `End` | |
| Combos (desktop/browser) | `ctrl+c` `ctrl+a` `alt+tab` `ctrl+shift+t` | modifiers `ctrl` `alt` `shift` `cmd` (= meta/win); join with `+` |
| Mobile (Android/iOS) | `Back` `Home` `Menu` `Enter` | single keys only, no combos |

So `bot.press_key(t, "Enter")` becomes an adb keycode on Android and a `{ENTER}`
SendKeys on Airtest Windows automatically; `ctrl+t`/`ctrl+w` switch the active
tab on Playwright (reassign the returned page).

**Smart `go_back` (Playwright):** if the current page has back history it goes
back in place; if it doesn't — e.g. a click opened a link in a **new tab**,
which starts with no history — and another tab is open, it closes the current
tab and returns to the previous one. So the common "click opens a video in a new
tab, then go back to the list" loop just works:

```python
for i in range(4):
    page = bot.click(page, locate=f"open video {i + 1}")  # opens a new tab
    bot.screenshot(page)
    page = bot.go_back(page)                               # closes it, back to the list
```

Reach for `close_tab` directly when you want to force-close the current tab
regardless of history.

Platform support (all actions):

| Action         | Playwright | Selenium | Appium (mobile) | pyautogui (desktop) | Airtest |
| -------------- | :--------: | :------: | :-------------: | :-----------------: | :-----: |
| `click`        |     ✅     |    ✅    |       ✅        |         ✅          |   ✅    |
| `double_click` |     ✅     |    ✅    |      ✅ ᵃ       |         ✅          |  ✅ ᵃ   |
| `right_click`  |     ✅     |    ✅    |    = tap ᵇ      |         ✅          | Windows / = tap ᵇ |
| `hover`        |     ✅     |    ✅    |    no-op ᶜ      |         ✅          | Windows / no-op ᶜ |
| `type_text`    |     ✅     |    ✅    |       ✅        |         ✅          |   ✅    |
| `clear_text`   |     ✅     |    ✅    |       ✅        |         ✅          | Android ᵈ |
| `press_key`    |     ✅     |    ✅    |       ✅        |         ✅          |  ✅ ᵉ   |
| `scroll`       |     ✅     |    ✅    |       ✅        |         ✅          |   ✅    |
| `drag`         |     ✅     |    ✅    |       ✅        |         ✅          |   ✅    |
| `navigate`     |     ✅     |    ✅    |       ✅        |         ❌          |   ❌    |
| `go_back`      |     ✅     |    ✅    |       ✅        |         ❌          | Android |
| `close_tab`    |     ✅     |    ❌    |       ❌        |         ❌          |   ❌    |
| `screenshot`   |     ✅     |    ✅    |       ✅        |         ✅          |   ✅    |

AI-located actions (`click`, `type_text`, `double_click`) and the AI operations
(`extract`, `verify`, `wait_for`, `ai`) work on **every** framework — the matrix
shows how each underlying action maps per platform.

- ᵃ Appium/Airtest emulate `double_click` as two quick taps.
- ᵇ Mobile has no right-click: Appium taps; Airtest right-clicks on Windows only, taps elsewhere.
- ᶜ Touch targets have no hover: Appium and Airtest Android/iOS treat `hover` as a no-op; Airtest moves the cursor (no click) on Windows.
- ᵈ Airtest has no element model; `clear_text` is best-effort on Android (caret-to-end + repeated delete).
- ᵉ Airtest maps common key names per platform automatically — Android/iOS to adb keycodes, Windows to pywinauto `SendKeys` (`{ENTER}`, `^c`); names outside the map pass through unchanged.

`navigate`/`go_back` raise `NotImplementedError` where unsupported (pyautogui has
no browser-style navigation; Airtest has no URL concept). `close_tab` is
Playwright-only (other targets raise `NotImplementedError`); the new-tab fallback
inside `go_back` therefore applies to Playwright only — on Selenium/Appium
`go_back` is always history-back, and on Airtest it maps to `keyevent("BACK")`
(Android only; iOS/Windows raise).

### Launch a Desktop App (No AI)

pyautogui can drive the mouse and keyboard but cannot open an application.
`launch_app` shells out to the OS so desktop runs can start from a known app:

```python
import pyautogui
from qirabot import Qirabot, launch_app

bot = Qirabot(task_name="wechat")

bot.launch_app("WeChat")              # macOS app name (or bundle id "com.tencent.xinWeChat")
# launch_app("notepad")              # Windows: exe path, registered name, or UWP AppUserModelID
# launch_app("/path/to/app", wait=3) # wait seconds for the window to appear (default 2)

bot.ai(pyautogui, "Send 'hello' to honey in WeChat")
```

`launch_app` is also available standalone (`from qirabot import launch_app`).
On macOS it uses `open -a`/`open -b` (activating an already-running app), on
Windows `os.startfile`/`start`/`explorer.exe shell:AppsFolder`, on Linux the
executable directly.

## Reports

By default every run writes a self-contained HTML report (with per-step
screenshots) when the bot closes — including on error or Ctrl+C, so you can see
where it stopped. No model calls, no network; it's built from data captured
during the run.

```python
# Default: report on, written to ./qira_runs/<date>/<time-id>/
bot = Qirabot(task_name="checkout")

# Custom output root (date/run subdirs are still added automatically)
bot = Qirabot(report_dir="./artifacts")        # or export QIRA_REPORT_DIR=./artifacts

# Turn it off entirely (nothing written to disk) — e.g. CI / library use
bot = Qirabot(report=False)
```

Output layout per run:

```
qira_runs/2026-06-07/192335-3f9ab2c1/
  report.html          # self-contained: embedded thumbnails + PASS/FAIL per ai() task
  screenshots/         # full-resolution frames (click a thumbnail to open)
    001_click.jpg
    002_type_text.jpg
    ...
  recording.mp4        # or recording.webm — embedded in the report if present
```

`screenshot_annotate=True` (default) draws a red crosshair at the resolved
click/type coordinates. To embed a screen recording, put a file named
`recording.mp4` or `recording.webm` into `bot.report_dir`. With an external
recorder, point it there directly:

```python
dev.start_recording(output=os.path.join(bot.report_dir, "recording.mp4"))
```

For a browser run, the SDK does not record for you — use Playwright's native
recording and save into `report_dir`. Create your own context with
`record_video_dir`, drive it through the bot, then rename the emitted file:

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    context = browser.new_context(record_video_dir=bot.report_dir)
    page = context.new_page()
    page.goto("https://example.com")
    bot.ai(page, "do the thing")               # drive the recorded page
    context.close()                            # flushes the .webm
    os.rename(page.video.path(), os.path.join(bot.report_dir, "recording.webm"))
```

Call `bot.report("path.html")` to also write the report to a custom location on
demand. Use `bot.screenshot(target)` for a one-off frame (saved under
`report_dir/screenshots/`).

## Bolt-On to Any Framework

Qirabot works with your existing automation setup — just pass your page/driver/device object:

### Playwright

```python
from playwright.sync_api import sync_playwright
from qirabot import Qirabot

bot = Qirabot()

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("https://github.com/trending")

    # Mix playwright selectors with AI
    repos = bot.extract(page, "Get the top 5 trending repo names")
    print(repos)

    browser.close()
bot.close()
```

### Selenium

```python
from selenium import webdriver
from qirabot import Qirabot

driver = webdriver.Chrome()
driver.get("https://www.wikipedia.org")
bot = Qirabot().bind(driver)   # bind once; the driver is stable for the session

summary = bot.extract("Get the first paragraph of the article")
print(summary)

driver.quit()
bot.close()
```

### Android (Appium)

```python
from appium import webdriver
from appium.options.android import UiAutomator2Options
from qirabot import Qirabot

options = UiAutomator2Options()
options.platform_name = "Android"
options.device_name = "emulator-5554"
options.app_package = "com.android.settings"
options.app_activity = ".Settings"
driver = webdriver.Remote("http://localhost:4723", options=options)
bot = Qirabot().bind(driver)

bot.click("Wi-Fi settings")
result = bot.ai("Open Display settings and change font size to Large")
print(f"Success: {result.success}")
bot.close()
driver.quit()
```

### Android / iOS / Windows (Airtest)

Airtest connects to the device itself (no Appium server). `G` resolves the
current device, so `bind(G)` keeps your usual Airtest style and adds AI on top.
The minimal form:

```python
from airtest.core.api import *       # your usual Airtest imports
from qirabot import Qirabot

auto_setup(__file__)                 # your usual Airtest setup, unchanged
bot = Qirabot().bind(G)

bot.click("Login button")            # AI-located — replaces brittle Template images
result = bot.ai("Open Settings and turn on dark mode")
print(f"Success: {result.success}")
touch(Template("native.png"))        # native Airtest still works side by side
bot.close()
```

#### Full Android example

A real run usually drives a specific app, streams steps, and records the screen.
This connects to an emulator/device over ADB, runs an AI task in Chinese, and
saves an Airtest screen recording into `bot.report_dir` so the HTML report embeds
it automatically:

```python
# -*- encoding=utf8 -*-
import os
from airtest.core.api import *
from airtest.cli.parser import cli_setup

from qirabot import Qirabot, StepResult

# When launched outside `airtest run ...`, set up the device ourselves.
# The connection string selects the device and touch backend (MAXTOUCH here).
if not cli_setup():
    auto_setup(
        __file__,
        logdir=True,
        devices=["android://127.0.0.1:5037/127.0.0.1:5555?touch_method=MAXTOUCH&"],
    )

# Credentials — prefer setting these in the environment, not in source.
# QIRA_BASE_URL is optional: it defaults to https://app.qirabot.com. Set it only
# for a self-hosted or regional deployment (the URL below is one such example).
os.environ.setdefault("QIRA_BASE_URL", "https://app.gcp.qirabot.com")
os.environ.setdefault("QIRA_API_KEY", "qk_...your_key...")

def on_step(step: StepResult) -> None:
    label = "done" if step.finished else step.action_type
    print(f"  step {step.step}: {label} {step.params}")

APP = "com.pokercity.lobby"
TASK = "Check that the UI controls at the top of the poker lobby work correctly"

start_app(APP)

# balanced_pro = stronger model; screenshot_annotate draws a crosshair at each tap.
bot = Qirabot(model_alias="balanced_pro", screenshot_annotate=True).bind(G)

# Record into the per-run dir so the report embeds it
# (qira_runs/<date>/<run>/recording.mp4).
video = os.path.join(bot.report_dir, "recording.mp4")
device().start_recording(output=video, max_time=1800)
try:
    result = bot.ai(TASK, max_steps=25, on_step=on_step, language="en")
    print(f" Result: {result.output}")
    sleep(5.0)
finally:
    saved = device().stop_recording(output=video)
    print(f" Recording saved: {saved}")
    bot.close()                       # writes report.html with the video embedded

stop_app(APP)
```

Notes on this example:

- **`cli_setup()` guard** lets the same file run both via `airtest run ...` (IDE /
  CI, which calls `cli_setup()` for you) and as a plain `python script.py`.
- **`bind(G)`** binds the bot to the current device, so `bot.ai(TASK, ...)` takes
  the instruction directly (no `target` argument). Bound calls accept
  `max_steps`, `on_step`, `model_alias`, and `language`.
- **`on_step`** fires after every action — use it for live logging or to push
  progress somewhere. `step.finished` marks the terminal step.
- **Recording** is done by Airtest's native `device().start_recording(...)`, not
  the SDK. Aim it at `bot.report_dir` and name it `recording.mp4` (or
  `recording.webm`) and the report picks it up — see [Reports](#reports).
- **`result.output`** is the model's final answer; `result.success` is the
  pass/fail verdict.

Trade-offs and capability notes (e.g. `navigate` unsupported, `go_back` Android-only)
are in [examples/airtest/](examples/airtest/). You can also pass `G`, the
`airtest.core.api` module, or an explicit `connect_device(...)` handle directly
without `bind()`.

## Error Handling

```python
from qirabot import (
    Qirabot,
    QirabotError,
    AuthenticationError,
    InsufficientBalanceError,
    QirabotTimeoutError,
)

try:
    bot = Qirabot()
    page = bot.open("https://example.com")
    bot.click(page, "Login button")
except AuthenticationError:
    print("Invalid API key.")
except InsufficientBalanceError:
    print("No credits left.")
except QirabotTimeoutError:
    print("Operation timed out.")
except QirabotError as e:
    print(f"Error: {e}")
finally:
    bot.close()
```

## Task Lifecycle

Each `Qirabot` instance manages a server-side task that tracks all operations:

- **Task creation**: created when the `Qirabot` instance is constructed (pass an existing `task_id` to attach to one instead)
- **Step recording**: each `click()`, `extract()`, `ai()` call is recorded as a step on the server
- **Task completion**: call `bot.close()` or use a context manager — the task is marked as completed
- **Auto-cleanup**: if `close()` is not called, `atexit` ensures cleanup on script exit. The server also has a 30-minute timeout for orphaned SDK tasks.

```python
bot = Qirabot(task_name="my automation")
# ... operations are recorded as steps ...
bot.close()  # task marked as completed
```

## Context Manager

```python
with Qirabot(task_name="my automation") as bot:
    page = bot.open("https://example.com")
    heading = bot.extract(page, "Get the main heading")
    print(heading)
# bot.close() is called automatically
```

## License

MIT
