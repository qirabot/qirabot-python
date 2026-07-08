# Qirabot Python SDK

Cross-platform GUI automation, driven by multimodal AI vision. Drive browsers, mobile apps, full desktops, and games through pixels — no DOM, no selectors — reaching what frameworks like Playwright, Selenium, and Appium cannot.

Run it standalone (`bot.open()` launches a browser for you), bolt it onto your existing Playwright / Selenium / Appium / Airtest / pyautogui session, drop it into a pytest suite, or bind by HWND to drive a Unity / Unreal / native desktop game. Same API across all of them.

**Contents:** [Installation](#installation) · [Quick Start](#quick-start) · [CLI](#cli) ·
[Bolt-On to Any Framework](#bolt-on-to-any-framework) · [API Reference](#api-reference) ·
[Reports](#reports) · [Configuration](#configuration) · [Error Handling](#error-handling) ·
[Agent Skill](#agent-skill)

## Installation

New to qirabot? Take the default path — browser automation, no other setup:

```bash
python3 -m venv .venv && source .venv/bin/activate   # recommended: a fresh virtualenv
python -m pip install "qirabot[browser]"
playwright install chromium      # one-time browser download
export QIRA_API_KEY="qk_your_api_key"   # from your dashboard: https://app.qirabot.com
qirabot doctor                   # optional: verify the environment end-to-end
```

Requires Python 3.10+. That's everything the [Quick Start](#quick-start) needs;
`bot.open()` launches the browser for you.

> **Using [uv](https://docs.astral.sh/uv/)?** The first two lines get shorter.
> For the CLI, `uv tool install "qirabot[browser]"` installs into its own
> isolated environment — no virtualenv to manage, and no pre-installed Python
> required (uv downloads one on demand). For library use (importing `qirabot`
> in your own tests), `uv venv && uv pip install "qirabot[browser]"` replaces
> the venv-and-pip lines above and sidesteps the
> `externally-managed-environment` error below entirely.

> Seeing `error: externally-managed-environment`? You're installing into the
> system Python (Debian/Ubuntu block that, per PEP 668) — create and activate a
> virtualenv as above, and prefer `python -m pip` over bare `pip` so the install
> always targets the interpreter that's actually active.

> On a fresh **Linux** machine, also run `sudo playwright install-deps chromium`
> once: the Chromium download doesn't include the system libraries it links
> against, so launch fails with `error while loading shared libraries:
> libnspr4.so ...` until they're installed. `qirabot doctor` detects this state
> and prints the same fix. And on a **display-less** box (headless server / VM,
> no `DISPLAY`), a visible browser window can't open — `bot.open()` and the CLI
> detect that and automatically run headless instead, with a warning.

**Already have an automation stack?** Then you don't need the browser extra at
all. The core package (`python -m pip install qirabot`) has no automation engine of its
own — it bolts onto the Playwright / Selenium / Appium / Airtest / pyautogui
session you already run, so your fixtures, CI, and device setup stay untouched
(see [Bolt-On to Any Framework](#bolt-on-to-any-framework)). Install the extra
matching your framework — or nothing, if the framework is already in your
environment:

```bash
python -m pip install "qirabot[desktop]"   # pyautogui (native desktop apps)
python -m pip install "qirabot[appium]"    # Appium (Android / iOS)
python -m pip install "qirabot[airtest]"   # Airtest (Android / iOS / Windows, image-based)

python -m pip install qirabot selenium     # Selenium is not an extra — bring your own driver
```

> Airtest itself declares no Python version, but its `numpy<2.0` pin means
> prebuilt wheels stop at **Python 3.12**. On 3.13+ pip builds numpy from
> source — that works with a C toolchain installed (verified on 3.14) and fails
> without one. Easiest path: **`qirabot[airtest]` on Python 3.10–3.12**, ideally
> in a fresh virtualenv — `uv venv --python 3.12` gets you one without touching
> the system Python. AirtestIDE (the standalone GUI) also targets 3.10–3.12.

Whichever path you took, `qirabot doctor` reports what is installed, what is
missing (with the exact command to fix it), and whether your API key reaches
the server.

## Quick Start

If you skipped it during [Installation](#installation): grab an API key from
your [dashboard](https://app.qirabot.com) and export it (a project `.env` file
works too — see [Configuration](#configuration)):

```bash
export QIRA_API_KEY="qk_your_api_key"
```

Then, with the default path installed ([Installation](#installation)), the
fastest way to see it work is one CLI command — no Python file needed:

```bash
qirabot browser "Search for SpaceX and get the first sentence of the article" --url wikipedia.org
```

That's a complete run: the browser opens, the AI does the task, and the result
(plus an HTML report) lands in your terminal. All commands and options are in
[CLI](#cli).

The same task through the Python SDK — the form you'll use to build real
automations. `bot.ai()` is the same engine the CLI command runs: the AI looks
at the screen, decides the next action, and loops until the task is done:

```python
from qirabot import Qirabot

bot = Qirabot()
page = bot.open("https://www.wikipedia.org")

result = bot.ai(page, "Search for SpaceX and get the first sentence of the article")
print(f"Success: {result.success}")
print(f"Result: {result.output}")

bot.close()
```

When you want to drive each step yourself instead of delegating the whole
task, the same natural-language targeting is available as single-step calls —
`bot.click(page, "Login button")`, `bot.type_text(...)`, `bot.extract(...)`,
`bot.verify(...)` — see [API Reference](#api-reference).

Every run also writes an HTML report with per-step screenshots (see
[Reports](#reports)), and every knob — model choice, language, recording,
timeouts — is a constructor option (see [Configuration](#configuration)).

## CLI

The `qirabot` command runs a task end-to-end without writing Python. It ships in
the core package (installed with `python -m pip install qirabot`), but each backend still
needs its extra — `qirabot[browser]` for `browser`, `[airtest]` for `android`/`ios`
(their default direct engine; `[appium]` when using `--engine appium`), `[desktop]`
for `desktop`.

```bash
# Browser (needs qirabot[browser] + `playwright install chromium`)
qirabot browser "Search for SpaceX and get the first sentence of the article" --url wikipedia.org

# Android — direct over adb (needs qirabot[airtest]; no Appium server)
qirabot android "Open settings and turn on airplane mode"

# iOS — direct to WebDriverAgent (needs qirabot[airtest] + WDA running on :8100).
# The device is picked by --wda-url, not by name; USB real device: `iproxy 8100 8100`
# first (see "iOS: real device vs simulator" below)
qirabot ios "Send hi to Alice on WeChat" --bundle-id com.tencent.xin

# Either can go through an Appium server instead (needs qirabot[appium])
qirabot android "..." --engine appium
qirabot ios "..." --engine appium --device "iPhone 15"   # simulators only — see below

# Desktop via pyautogui (needs qirabot[desktop])
qirabot desktop "Create a new note titled Groceries" --app Notes

# Environment check — what's installed, what's missing, is the server reachable
qirabot doctor

# Read-only server queries
qirabot task <task_id>            # status, commands, steps
qirabot screenshot <task_id>      # download a screenshot (auto-named; use -o to choose a path)
qirabot models                    # list model aliases
```

**Commands**

| Command | Purpose |
|---|---|
| `browser INSTRUCTION` | Run an AI task in a local browser (Playwright) |
| `android INSTRUCTION` | Run an AI task on an Android device (adb direct; `--engine appium` for Appium) |
| `ios INSTRUCTION` | Run an AI task on an iOS device (WDA direct; `--engine appium` for Appium) |
| `desktop INSTRUCTION` | Run an AI task on the desktop screen (pyautogui) |
| `doctor` | Check Python, API key/server, and per-backend dependencies; exits non-zero when nothing can run |
| `task TASK_ID` | Print a task's status, commands, and steps |
| `screenshot TASK_ID` | Download a task screenshot |
| `models` | List available model aliases |

**Global options** go **before** the subcommand (they configure the connection):

```bash
qirabot --api-key qk_... --base-url https://app.qirabot.com browser "..."
```

`--api-key` / `--base-url` fall back to `QIRA_API_KEY` / `QIRA_BASE_URL`; also
available are `--timeout` and `--verify-ssl` / `--no-verify-ssl`. The CLI loads a
project `.env` automatically (same rules as [`load_dotenv`](#configuration):
`$QIRA_DOTENV` or `./.env`; exported variables win). Run `qirabot -h`
or `qirabot <command> -h` for the full, default-annotated option list.

**Exit codes** are script-friendly: `0` task succeeded, `1` task failed or any
error, `130` interrupted with Ctrl+C — so `qirabot browser "..." && next-step`
only proceeds on success.

**Shared run options** (`browser` / `android` / `ios` / `desktop`): `-n/--name` (defaults to
the instruction text), `-m/--model`, `-l/--language`, `--max-steps`,
`--report/--no-report`, `--report-dir`, `--annotate/--no-annotate`. All four also
take `--record`, saving `recording.mp4` into the run dir and embedding it in the
report — but what gets recorded differs:

- `browser` / `desktop` — the **host** screen via ffmpeg (needs ffmpeg on PATH).
- `android` — the **device** screen: `adb screenrecord` on the default engine
  (ffmpeg only needed to merge runs longer than 3 minutes), or Appium's
  recording API with `--engine appium`.
- `ios` — the **device** screen: WDA's MJPEG stream on the default engine
  (needs ffmpeg; a USB real device also needs `iproxy 9100 9100` alongside the
  usual 8100 forward — the CLI checks the stream before starting and tells you
  if it isn't reachable), or Appium's recording API with `--engine appium`.
  `--mjpeg-url` overrides the stream URL (default: the `--wda-url` host on
  port 9100).

Runs also honor the same env vars as the SDK — `QIRA_REPORT_DIR`,
`QIRA_SETTLE_SECONDS`, `QIRA_RECORD*`, etc. (see [Configuration](#configuration)).

**iOS: real device vs simulator.** The two engines target different things — pick
by what you're driving:

- **Real device → default (WDA direct) engine.** The device is selected by
  `--wda-url`, not by a device name (`-d` is rejected here). Three steps:
  1. Run WebDriverAgent on the phone and keep it running — in Xcode, run the
     `WebDriverAgentRunner` scheme against the device with your own signing team
     (or `xcodebuild ... -destination 'id=<udid>' -allowProvisioningUpdates test`).
  2. Forward the port over USB: `iproxy 8100 8100` (from `libimobiledevice`).
     Sanity check: `curl http://127.0.0.1:8100/status` returns JSON.
  3. `qirabot ios "..." --bundle-id com.example.app` — the default `--wda-url`
     (`http://127.0.0.1:8100`) now reaches the phone. For multiple devices, run
     one `iproxy` per device on different local ports and select with `--wda-url`.
- **Simulator → `--engine appium`.** Here `-d/--device` is a *simulator device
  type* (a name from `xcrun simctl list devicetypes`, e.g. `iPhone 15`) — Appium
  creates/boots a matching simulator. It is **not** a real device's name: the CLI
  currently has no `--udid` option, so the appium engine cannot target real iOS
  devices; passing a real device's name fails with
  `Could not create simulator ... device type id '<your name>'`.

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
This connects to an emulator/device over ADB, runs an AI task, and records the
**device** screen into `bot.report_dir` so the HTML report embeds it
automatically: `record=True, record_device=True` picks the device's own
recorder (`adb screenrecord` here — see
[Screen recording](#screen-recording)) instead of capturing the host screen a
headless device doesn't appear on:

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

# balanced_pro = stronger model; screenshot_annotate draws a crosshair at each
# tap; record_device records the phone screen via adb screenrecord (recording
# starts with the first action and stops in bot.close()).
bot = Qirabot(
    model_alias="balanced_pro", screenshot_annotate=True,
    record=True, record_device=True,
).bind(G)

try:
    result = bot.ai(TASK, max_steps=25, on_step=on_step, language="en")
    print(f" Result: {result.output}")
    sleep(5.0)
finally:
    bot.close()                       # stops recording, writes report.html with the video embedded

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
- **Recording** uses `record=True, record_device=True`: the recorder is picked
  from the device (`adb screenrecord` for airtest Android), runs on the phone,
  and `bot.close()` pulls the video into `bot.report_dir` as `recording.mp4`
  (see [Screen recording](#screen-recording)). Airtest's native
  `device().start_recording(...)` aimed at the same path still works if you
  prefer it.
- **`result.output`** is the model's final answer; `result.success` is the
  pass/fail verdict, and `result.status` says how the run ended (see
  [Error Handling](#error-handling)).

Trade-offs and capability notes (e.g. `navigate` unsupported, `go_back` Android-only)
are in [examples/airtest/](examples/airtest/). You can also pass `G`, the
`airtest.core.api` module, or an explicit `connect_device(...)` handle directly
without `bind()`.

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

Runnable examples live in [examples/](examples/), in three styles:

- **Bolt onto your existing tests (pytest)** — add AI to a suite you already
  have: [playwright/](examples/playwright/), [selenium/](examples/selenium/),
  [appium/](examples/appium/), [desktop/](examples/desktop/).
- **Standalone automation (plain scripts)** — scraping / RPA / agents, run with
  `python`: [automation/](examples/automation/).
- **Drive a desktop game (Windows)** — bind by HWND, audit in-game UI with
  deterministic steps + `bot.ai()`: [game/](examples/game/).

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

So `bot.press_key(t, "Enter")` becomes an adb keycode on Android and a
DirectInput scancode on Airtest Windows automatically; `ctrl+t`/`ctrl+w` switch
the active tab on Playwright (reassign the returned page).

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
| `long_press`   |     ❌ ᶠ    |    ❌ ᶠ   |       ✅        |         ❌ ᶠ         |   ✅    |
| `mouse_down`   |     ❌ ᵍ    |    ❌ ᵍ   |       ❌ ᵍ      |         ✅          | Windows |
| `mouse_up`     |     ❌ ᵍ    |    ❌ ᵍ   |       ❌ ᵍ      |         ✅          | Windows |
| `key_down`     |     ❌ ᵍ    |    ❌ ᵍ   |       ❌ ᵍ      |         ✅          | Windows |
| `key_up`       |     ❌ ᵍ    |    ❌ ᵍ   |       ❌ ᵍ      |         ✅          | Windows |
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
- ᵉ Airtest maps common key names per platform automatically — Android/iOS to adb keycodes, Windows to DirectInput scancodes (real hardware-level keys, so games that read raw scancodes receive them, incl. `ctrl`/`alt`/`win` combos), falling back to pywinauto `SendKeys` only for keys scancodes can't express (e.g. shifted symbols like `!`, F13+).
- ᶠ `long_press` is a touch-only gesture (Appium/Airtest mobile); the server only offers it on Android/iOS. Browser/desktop adapters raise `NotImplementedError`.
- ᵍ `mouse_down`/`mouse_up`/`key_down`/`key_up` are desktop-only split press/release primitives (pyautogui, plus Airtest on Windows) for holding an input across other actions — hold a key to keep moving in a game, press-and-hold the mouse to drag, etc. Pair each press with its release; as a safety net any input still held is auto-released at the end of an `ai()` run and on `close()`. `mouse_up`'s locate is optional (omit to release at the current cursor; `bot.mouse_up(target)` is then deterministic — no AI, no billing — like `key_down`/`key_up`). Browser/mobile adapters raise `NotImplementedError`.

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
  report.html          # self-contained: embedded thumbnails + outcome badge per ai() task
  screenshots/         # full-resolution frames (click a thumbnail to open)
    001_click.jpg
    002_type_text.jpg
    ...
  recording.mp4        # screen recording (host or device) — embedded in the report if present
```

Each `ai()` task gets an outcome badge matching `result.status` (see
[Error Handling](#error-handling)): green `PASS`, red `FAIL` / `ERROR`, or amber
`MAX STEPS` for step-budget truncations. The header summary is green when
everything passed, amber when the only misses are truncations, red when
anything truly failed.

`screenshot_annotate=True` (default) draws a red crosshair at the resolved
click/type coordinates.

### Screen recording

Pass `record=True` and the SDK records the full screen with ffmpeg for the whole
run, saving `recording.mp4` into `bot.report_dir` and embedding it in the report
— no matter which framework you drive:

```python
bot = Qirabot(record=True)          # or set QIRA_RECORD=1
page = bot.open("https://example.com")
bot.ai(page, "do the thing")
bot.close()                         # stops recording, then writes the report
```

Or control it manually (works with `record=False` too):

```python
bot.start_recording()               # idempotent; fps via record_fps / start_recording(fps=...)
try:
    bot.ai(page, "do the thing")
finally:
    bot.stop_recording()            # one recording per run — restarting overwrites recording.mp4
```

Requires the `ffmpeg` binary on PATH (`brew install ffmpeg` /
`choco install ffmpeg` / `apt install ffmpeg`); on macOS grant the terminal/IDE
"Screen Recording" permission or it captures a black screen. Recording is
best-effort: a missing ffmpeg or denied permission only warns and never fails
the task (check `recording.ffmpeg.log` in the run dir). Dropping your own
`recording.mp4` into `report_dir` is still embedded just the same.

**Device recording (android / ios).** The default recorder captures the *host*
screen, which a phone doesn't appear on. Two switches record the device's own
screen instead (both used by the CLI's `android`/`ios --record`):

```python
# Android (or any Appium driver): the recorder is picked from the action target.
bot = Qirabot(record=True, record_device=True)   # or QIRA_RECORD_DEVICE=1
bot.ai(dev, "open settings")   # airtest Android -> adb screenrecord
bot.close()                    # pulls the video into report_dir/recording.mp4

# iOS via WDA (no Appium): record WDA's MJPEG stream (port 9100; USB real
# device: `iproxy 9100 9100`). Needs ffmpeg on the host.
bot = Qirabot(record=True, record_mjpeg_url="http://127.0.0.1:9100")
```

- `record_device=True` defers the start until the first action, then resolves a
  recorder from its target: an **Appium driver** (android *and* ios) uses
  Appium's session recording API; an **airtest Android** device uses
  `adb screenrecord` on the phone (segments beyond screenrecord's 3-minute cap
  are merged with ffmpeg — without ffmpeg only the first segment is kept, with
  a warning). Unsupported targets skip recording rather than silently capturing
  the wrong (host) screen. If you quit an Appium driver yourself, call
  `bot.stop_recording()` first — the video lives in the session.
- `record_mjpeg_url=...` records any MJPEG-over-HTTP stream with ffmpeg —
  in practice WDA's device-screen stream for iOS runs driven directly through
  WDA, where there is no Appium session to record with.

**Per-window capture + system audio (Windows).** On Windows you can record just
the window under test and capture its sound:

```python
from airtest.core.api import connect_device
dev = connect_device("Windows:///?title_re=Notepad.*")   # a concrete window
bot = Qirabot(record=True, record_window=True, record_audio=True)
bot.ai(dev, "type a note")          # recording starts here, following the window
bot.close()                         # recording.mp4 = just that window, with sound
```

- `record_window=True` records only the window under test instead of the whole
  desktop. The window is resolved automatically from the action target, so it
  only works with the **airtest Windows** backend (other backends and any
  resolution failure fall back to full screen). You can also target a window
  explicitly with `bot.start_recording(window="Window Title")`, which works for
  any Windows backend. Keep the window visible — `gdigrab` produces black/frozen
  frames for a minimized, occluded, or GPU-composited (game) window; for games,
  record full screen instead.
- `record_audio=True` records **system audio**. ffmpeg has no native loopback on
  Windows, so this needs a DirectShow source that exposes the system mix —
  install [screen-capture-recorder](https://github.com/rdp/screen-capture-recorder-to-video-windows-free)
  (provides `virtual-audio-capturer`) or enable "Stereo Mix" in the Sound
  control panel. The device is auto-detected; override with a specific name via
  `record_audio="My Device"` or `QIRA_AUDIO_DEVICE`. List candidates with
  `ffmpeg -list_devices true -f dshow -i dummy`. If none is found it records
  silently with a warning. If audio lags the video, nudge it with
  `record_audio_offset=-0.4` (or `QIRA_AUDIO_OFFSET`).

**Multiple monitors (macOS).** The full screen is captured one display at a
time; by default that's the primary display (`Capture screen 0`). To record a
different one, set `QIRA_SCREEN_INDEX` to its avfoundation device index:

```bash
# List the screen devices and their indices first:
ffmpeg -f avfoundation -list_devices true -i ""
#   [1] Capture screen 0   <- primary (default)
#   [2] Capture screen 1   <- second monitor

QIRA_SCREEN_INDEX=2 python reddit.py     # record the second monitor
```

Make sure the window you care about is on the recorded display — with
`headless=False` the browser opens wherever macOS places it. On Windows/Linux
the default already grabs the whole virtual desktop (all monitors), so this knob
is macOS-only.

Call `bot.report("path.html")` to also write the report to a custom location on
demand. Use `bot.screenshot(target)` for a one-off frame (saved under
`report_dir/screenshots/`).

## Configuration

```bash
export QIRA_API_KEY="qk_your_api_key"
```

```python
from qirabot import Qirabot

bot = Qirabot()  # reads QIRA_API_KEY from environment
```

Settings can also live in a project `.env` file. Scripts opt in explicitly —
`from qirabot import load_dotenv; load_dotenv()` — which reads `$QIRA_DOTENV` or
`./.env` and never overrides exported variables; the `qirabot` CLI loads it
automatically.

Constructor options:

| Parameter | Env Variable | Default | Description |
|---|---|---|---|
| `api_key` | `QIRA_API_KEY` | — | API key for authentication |
| `base_url` | `QIRA_BASE_URL` | `https://app.qirabot.com` | API server URL |
| `timeout` | — | `120.0` | HTTP request timeout (seconds) |
| `verify_ssl` | — | `True` | Verify the server's TLS certificate (set `False` for self-hosted / self-signed) |
| `model_alias` | — | `balanced_pro` | Model alias for all operations; pass `""` for the server default |
| `language` | — | server default | Response language, e.g. `"zh"` / `"en"`; `""` = server default |
| `task_name` | — | `""` | Optional name for the task (visible in dashboard) |
| `report` | — | `True` | Write an HTML run report (+ screenshots) on close |
| `report_dir` | `QIRA_REPORT_DIR` | `./qira_runs/<date>/<time-id>/` | Output root; the `<date>/<time-id>/` subdirs are always appended |
| `record` | `QIRA_RECORD` | `False` | Record the screen with ffmpeg into `recording.mp4` (embedded in the report) |
| `record_fps` | — | `12` | Recording frame rate |
| `record_window` | `QIRA_RECORD_WINDOW` | `False` | **Windows + airtest only.** Record just the window under test (auto-resolved from the first action) instead of the full screen; falls back to full screen otherwise |
| `record_audio` | `QIRA_RECORD_AUDIO` | `False` | **Windows only.** Capture system audio into the recording. `True` auto-detects a loopback device, or pass a DirectShow device name |
| `record_audio_offset` | `QIRA_AUDIO_OFFSET` | `None` | A/V sync offset in seconds (usually negative, e.g. `-0.4`) applied to the audio input |
| `record_device` | `QIRA_RECORD_DEVICE` | `False` | Record the automated **device's** screen instead of the host's: Appium driver → session recording API, airtest Android → `adb screenrecord` (resolved from the first action's target) |
| `record_mjpeg_url` | `QIRA_RECORD_MJPEG_URL` | `None` | Record this MJPEG-over-HTTP stream instead of the host screen (e.g. WDA's iOS device stream on port 9100); needs ffmpeg |
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
| `balanced` | Good cost/quality balance |
| `balanced_pro` | The default — stronger than `balanced` |
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
text = bot.extract(page, "Get the main heading", language="zh")
```

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

### How an ai() run ended: `result.status`

`result.success` is the two-state pass/fail verdict, but a failed run can mean
very different things. `result.status` says which one you got:

| status | meaning | `success` |
|---|---|---|
| `"completed"` | model declared the goal achieved | `True` |
| `"goal_failed"` | model concluded the goal is unreachable (login wall, captcha) | `False` |
| `"max_steps"` | step budget ran out before the model finished — a truncation, not a capability verdict | `False` |
| `"error"` | the server reported a terminal error | `False` |

```python
result = bot.ai(page, "Find the cheapest flight and hold it")
if result.status == "max_steps":
    # not a real failure — the budget was too small; retry with headroom
    result = bot.ai(page, "Find the cheapest flight and hold it", max_steps=50)
```

Runs that end by raising (e.g. `ActionError`) never produce a `RunResult`; in
the report their section is badged `ERROR`.

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

Or let a context manager close it:

```python
with Qirabot(task_name="my automation") as bot:
    page = bot.open("https://example.com")
    heading = bot.extract(page, "Get the main heading")
    print(heading)
# bot.close() is called automatically
```

## Agent Skill

The `plugins/qirabot/skills/qirabot/` directory is a **pre-built agent skill** — a
self-contained bundle an AI agent can load to write, run, and debug Qirabot
automations. Instead of describing the API in a chat, you state the automation
goal and the agent handles setup, scripting, and verification.

### Install in Claude Code

The skill is packaged as a Claude Code plugin (`plugins/qirabot/`) and published
through the lightweight [`qirabot/claude-plugins`](https://github.com/qirabot/claude-plugins)
marketplace, which fetches **only this subdirectory** (via a `git-subdir` source)
— users never clone the whole SDK:

```text
/plugin marketplace add qirabot/claude-plugins
/plugin install qirabot@qirabot
```

Once installed the skill is available as `/qirabot:qirabot` and Claude invokes it
automatically for UI automation tasks. The `qirabot` pip package is installed at
runtime by the skill's own `scripts/preflight.py`.

### Skill layout

The plugin bundles the skill (`SKILL.md`) plus its preflight script, condensed
API reference, and starter templates (browser / Android / bring-your-own-driver).
See [plugins/qirabot/README.md](plugins/qirabot/README.md) for the full tree.

### How the skill works

1. **Preflight first** — before writing any code the agent runs `scripts/preflight.py`
   to confirm Python version, `QIRA_API_KEY`, and target-specific dependencies:

   ```bash
   python scripts/preflight.py browser     # or: android | ios | desktop
   ```

   If anything is missing, it prints exactly what to fix.

2. **Pick a template** — the agent copies the starter that matches the target
   (browser, Android, or bring-your-own-driver) and fills in the task.

3. **Verify from the report** — after running, the agent opens the HTML report
   (`qira_runs/<date>/<run>/report.html`) to confirm what actually happened on
   screen, rather than trusting the script's return value alone.

The skill's reference and templates are drift-tested against the live SDK in CI
(`tests/test_skill.py`), so renamed methods or changed constructor kwargs fail
here instead of silently breaking an automation run.

## License

MIT
