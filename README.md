# Qirabot Python SDK

AI-powered automation SDK that bolts onto your existing browser/mobile automation framework. Let AI see the screen, click, type, extract data, and verify results — with any framework you already use.

Use it three ways: as a **Python library** (launch your own browser or bolt onto Playwright / Selenium / Appium / pyautogui), inside your **pytest suite**, or straight from the **terminal** via the `qirabot` CLI — no code required.

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
pip install "qirabot[all]"       # everything above + the CLI
```

The Quick Start below uses `bot.open()`, so it needs `qirabot[browser]` plus a
one-time `playwright install chromium`. Selenium isn't an extra — install it
yourself (`pip install selenium`) and pass your own driver.

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
| `screenshot_dir` | `QIRA_SCREENSHOT_DIR` | `""` | Save screenshots locally for debugging |
| `screenshot_annotate` | — | `False` | Draw a red crosshair at click/type coordinates |
| `screenshot_format` | — | `"jpeg"` | Saved screenshot format (`"jpeg"` or `"png"`) |
| `screenshot_quality` | — | `80` | JPEG quality, 1–100 |
| `retry` | — | `1` | Retries per action on transient failures |
| `retry_delay` | — | `1.0` | Seconds between retries |

## Quick Start

```python
from qirabot import Qirabot

bot = Qirabot()
page = bot.open("https://google.com")

bot.type_text(page, "Search input", "qirabot")
bot.click(page, "Search button")

summary = bot.extract(page, "Get the first search result title")
print(f"Result: {summary}")

bot.close()
```

## Examples

Runnable examples live in [examples/](examples/), in two styles:

- **Bolt onto your existing tests (pytest)** — add AI to a suite you already
  have: [playwright/](examples/playwright/), [selenium/](examples/selenium/),
  [appium/](examples/appium/), [desktop/](examples/desktop/).
- **Standalone automation (plain scripts)** — scraping / RPA / agents, run with
  `python`: [automation/](examples/automation/).

See [examples/README.md](examples/README.md) for which to pick.

## CLI

Run AI tasks from the terminal without writing any Python. Installs as the
`qirabot` command:

```bash
pip install "qirabot[cli]"   # adds the CLI (included in [all])
export QIRA_API_KEY="qk_..."
```

```bash
# Drive a local browser with a natural-language task
qirabot browse "Search Hacker News for 'rust' and list the top 3 titles"
qirabot browse "Extract the trending repos" --url https://github.com/trending --headless

# Connect to a Chrome you already have open (started with --remote-debugging-port=9222)
qirabot browse "Summarize this page" --cdp http://localhost:9222

# Mobile (Appium) and desktop (pyautogui)
qirabot mobile "Open Display settings and turn on dark mode" --platform android
qirabot mobile "Send 'hi' to honey" --platform ios --bundle-id com.tencent.xin
qirabot desktop "Type 42 + 58 = in Calculator and read the result"
qirabot desktop "Send 'hi' to honey in WeChat" --app WeChat --app-wait 3

# Inspect tasks and account
qirabot task <task_id>                       # status + steps
qirabot screenshot <task_id> -s 2 -o shot.png
qirabot models                               # list available model aliases
```

`browse` needs `qirabot[browser]`, `mobile` needs `qirabot[appium]`, `desktop`
needs `qirabot[desktop]`. Run `qirabot --help` or `qirabot <command> --help` for
all options.

## API Reference

### Simple Actions

These actions use lightweight vision-based element location — fast and low-cost:

```python
# Click on an element by description
bot.click(page, "Login button")

# Type text into an input field
bot.type_text(page, "Email input", "user@example.com")

# Extract data from the screen
text = bot.extract(page, "Get the main heading")

# Verify a visual assertion (returns True/False)
ok = bot.verify(page, "The success message is visible")

# Wait for a condition with timeout
ready = bot.wait_for(page, "Page has finished loading", timeout=15.0, interval=2.0)
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
    "Search for 'best python libraries 2025', click the first result, and extract the main content",
    max_steps=10,
    on_step=on_step,
)

print(f"Success: {result.success}")
print(f"Output: {result.output}")
bot.close()
```

### Screenshot (No AI)

Saves to `screenshot_dir` and returns the saved path (or `None` if no
`screenshot_dir` is configured):

```python
path = bot.screenshot(page)
print(f"saved to {path}")
```

### Navigation & Scrolling (No AI)

Direct, non-billed actions that don't need AI element location. `go_back`,
`navigate`, and `close_tab` return the current page/target (may differ after the
navigation); `scroll` returns `None`.

```python
bot.navigate(page, "example.com")   # scheme optional; "https://" prepended
bot.go_back(page)                   # back to the previous page (smart, see below)
page = bot.close_tab(page)          # close current tab, return to previous tab
bot.scroll(page, "down", 3)         # scroll at viewport center
bot.scroll(page, "up", distance=5, x=640, y=400)  # scroll at a point
```

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

Platform support:

| Method      | Playwright | Selenium | Appium (mobile) | pyautogui (desktop) |
| ----------- | :--------: | :------: | :-------------: | :-----------------: |
| `navigate`  |     ✅     |    ✅    |       ✅        |         ❌          |
| `go_back`   |     ✅     |    ✅    |       ✅        |         ❌          |
| `close_tab` |     ✅     |    ❌    |       ❌        |         ❌          |
| `scroll`    |     ✅     |    ✅    |       ✅        |         ✅          |

`navigate`/`go_back` raise `NotImplementedError` on desktop (pyautogui), which
has no browser-style navigation. `close_tab` is Playwright-only (other targets
raise `NotImplementedError`); the new-tab fallback inside `go_back` therefore
applies to Playwright only — on Selenium/Appium `go_back` is always history-back.

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

## Debugging Screenshots

Save screenshots locally to see exactly what the AI sees at each step:

```python
# Save raw screenshots
bot = Qirabot(screenshot_dir="./screenshots")

# Save screenshots with red crosshair markers at click/type coordinates
bot = Qirabot(screenshot_dir="./screenshots", screenshot_annotate=True)

# Or via environment variable
# export QIRA_SCREENSHOT_DIR=./screenshots
```

With `screenshot_annotate=True`, click/type_text screenshots include a red crosshair at the resolved coordinates, making it easy to verify targeting accuracy.

Screenshots are saved as sequentially numbered files:

```
screenshots/
  001_click_x245_y112.jpg
  002_type_text_x500_y300.jpg
  003_extract.jpg
  004_ai_step1.jpg
  005_ai_step2.png
  ...
```

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

bot = Qirabot()
driver = webdriver.Chrome()
driver.get("https://www.wikipedia.org")

summary = bot.extract(driver, "Get the first paragraph of the article")
print(summary)

driver.quit()
bot.close()
```

### Android (Appium)

```python
from appium import webdriver
from appium.options.android import UiAutomator2Options
from qirabot import Qirabot

bot = Qirabot()
options = UiAutomator2Options()
options.platform_name = "Android"
options.device_name = "emulator-5554"
options.app_package = "com.android.settings"
options.app_activity = ".Settings"
driver = webdriver.Remote("http://localhost:4723", options=options)

bot.click(driver, "Wi-Fi settings")
result = bot.ai(driver, "Open Display settings and change font size to Large")
print(f"Success: {result.success}")
bot.close()
driver.quit()
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

## Task Lifecycle

Each `Qirabot` instance manages a server-side task that tracks all operations:

- **Task creation**: automatically created on the first AI operation (lazy init)
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
