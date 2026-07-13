# Qirabot Python SDK

Cross-platform GUI automation, driven by multimodal AI vision. Drive browsers, mobile apps, full desktops, and games through pixels — no DOM, no selectors — reaching what frameworks like Playwright, Selenium, and Appium cannot.

Run it standalone (`bot.open()` launches a browser for you; Android / iOS / Windows-window backends are built in with zero extra dependencies), bolt it onto your existing Playwright / Selenium / Appium / pyautogui session, drop it into a pytest suite, or bind by HWND to drive a Unity / Unreal / native desktop game. Same API across all of them.

**📖 Full documentation: [qirabot.com/docs](https://qirabot.com/docs/)** ([中文](https://qirabot.com/docs/zh/))

## Installation

One line — installs [uv](https://docs.astral.sh/uv/), qirabot (isolated, never
touches your system Python), and Chromium. No pre-installed Python required:

```bash
# macOS / Linux
curl -LsSf https://qirabot.com/install | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://qirabot.com/install.ps1 | iex"
```

Driving a device instead of a browser? The Android (adb), iOS (WDA), and
Windows single-window backends are built into the core package:

```bash
uv tool install qirabot        # Android + iOS + Windows window; zero extras
```

pip, virtualenvs, per-framework extras, and troubleshooting:
[Installation guide](https://qirabot.com/docs/guide/installation.html).
Whichever path you took, `qirabot doctor` reports what is installed, what is
missing (with the exact fix), and whether your API key reaches the server.

## Quick Start

Save your API key once (get it from your
[dashboard](https://app.qirabot.com)), then hand the AI a task:

```bash
qirabot login
qirabot browser "Search for SpaceX and get the first sentence of the article" --url wikipedia.org
```

The same task through the Python SDK — `bot.ai()` is the same engine: the AI
looks at the screen, decides the next action, and loops until the task is
done:

```python
from qirabot import Qirabot

bot = Qirabot()
page = bot.open("https://www.wikipedia.org")

result = bot.ai(page, "Search for SpaceX and get the first sentence of the article")
print(f"Success: {result.success}")
print(f"Result: {result.output}")

bot.close()
```

Prefer to drive each step yourself? The same natural-language targeting works
as single-step calls — `bot.click(page, "Login button")`,
`bot.extract(...)`, `bot.verify(...)` — with your code in control. Every run
writes an HTML report with per-step screenshots; `--record` captures a video.

## Bolt onto your existing stack

No rewrite: pass your existing `page` / `driver` / device object and mix AI
steps with the selectors you already have —

```python
from qirabot import Qirabot

bot = Qirabot(task_name="test-checkout")

def test_checkout(page):          # your existing pytest-playwright fixture
    page.goto("https://shop.example.com")
    page.fill("#username", "test_user")             # your selectors, as-is
    page.click("#login-btn")

    assert bot.verify(page, "Product listing page is displayed")   # AI assertion

    result = bot.ai(page, "Complete checkout, name John Doe zip 10001", max_steps=8)
    assert result.success
```

Works the same for Selenium, Appium, pyautogui, and the built-in device
backends (`AdbDevice`, `WdaClient`, `Window`) — and anything else via a
7-primitive [custom adapter](https://qirabot.com/docs/backends/custom-adapters.html).

## Documentation

| Topic | |
|---|---|
| Getting started | [Installation](https://qirabot.com/docs/guide/installation.html) · [Quick Start](https://qirabot.com/docs/guide/quickstart.html) · [CLI Reference](https://qirabot.com/docs/guide/cli.html) |
| Platform backends | [Browser](https://qirabot.com/docs/backends/browser.html) · [Android (adb, no Appium)](https://qirabot.com/docs/backends/android.html) · [iOS (WDA, no Appium)](https://qirabot.com/docs/backends/ios.html) · [Windows & Games (DirectInput)](https://qirabot.com/docs/backends/windows-games.html) · [Desktop](https://qirabot.com/docs/backends/desktop.html) · [Custom Adapters](https://qirabot.com/docs/backends/custom-adapters.html) |
| Framework bolt-on | [Playwright](https://qirabot.com/docs/frameworks/playwright.html) · [Selenium](https://qirabot.com/docs/frameworks/selenium.html) · [Appium](https://qirabot.com/docs/frameworks/appium.html) · [pytest](https://qirabot.com/docs/frameworks/pytest.html) |
| Advanced | [AI Tasks & Custom Tools](https://qirabot.com/docs/advanced/ai-tasks.html) · [Reports & Recording](https://qirabot.com/docs/advanced/reports.html) · [Configuration](https://qirabot.com/docs/advanced/configuration.html) · [Error Handling](https://qirabot.com/docs/advanced/error-handling.html) |
| Reference | [API — Actions & Platform Matrix](https://qirabot.com/docs/reference/api.html) |

## Examples

Runnable examples live in [examples/](examples/), in three styles:

- **Bolt onto your existing tests (pytest)** — [playwright/](examples/playwright/),
  [selenium/](examples/selenium/), [appium/](examples/appium/),
  [desktop/](examples/desktop/)
- **Standalone automation (plain scripts)** — scraping / RPA / agents:
  [automation/](examples/automation/)
- **Drive a desktop game (Windows)** — bind by HWND, deterministic steps +
  `bot.ai()`: [game/](examples/game/)

See [examples/README.md](examples/README.md) for which to pick.

## Agent Skill

`plugins/qirabot/skills/qirabot/` is a pre-built agent skill: an AI agent
(Claude Code, Cursor, …) loads it and handles setup, scripting, and
verification from a natural-language automation goal. Install in Claude Code:

```text
/plugin marketplace add qirabot/claude-plugins
/plugin install qirabot@qirabot
```

The skill's reference and templates are drift-tested against the live SDK in
CI (`tests/test_skill.py`). Details: [plugins/qirabot/README.md](plugins/qirabot/README.md).

## Migrating from 1.x (airtest)

2.0 removed the airtest integration; the built-in backends are drop-in
replacements (`AdbDevice` / `WdaClient` / `Window`), and a copyable adapter
keeps existing airtest scripts running unchanged. Guide:
[Custom Adapters — Migrating from Airtest](https://qirabot.com/docs/backends/custom-adapters.html#migrating-from-airtest-qirabot-1-x).
The 1.x series lives on the [`1.x` branch](https://github.com/qirabot/qirabot-python/tree/1.x)
in maintenance mode — `pip install "qirabot<2"` always resolves to the newest
1.9.x patch.

## License

MIT
