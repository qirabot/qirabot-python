# Qirabot Python SDK

English | [简体中文](README.zh.md)

Cross-platform GUI automation, driven by multimodal AI vision. Drive browsers, mobile apps, full desktops, and games through pixels — no DOM, no selectors — reaching what frameworks like Playwright, Selenium, and Appium cannot.

Run it standalone (`bot.open()` launches a browser for you; Android / iOS / Windows-window backends are built in with zero extra dependencies), bolt it onto your existing Playwright / Selenium / Appium / pyautogui session, drop it into a pytest suite, or bind by HWND to drive a Unity / Unreal / native desktop game. Same API across all of them.

**📖 Full documentation: [qirabot.com/docs](https://qirabot.com/docs/)** ([中文](https://qirabot.com/docs/zh/))

## See it work

https://github.com/user-attachments/assets/649ea80c-63e7-4c85-9ee8-3c8fe17e5ef4

**Play an MMORPG from zero to level 15, hands-free** — iOS real device.
The entire task prompt is one sentence: *"This is Fantasy Westward Journey
mobile. Create a character, then complete the new-player flow; skip whatever
can be skipped."* Highlights cut from a single unedited run:
[full 5:50 video](https://qirabot.com/#demos) ·
[script](examples/game/ios_appium_mmorpg.py)

More real, unedited runs — the AI sees only pixels. Click a poster to watch
([all demos →](https://qirabot.com/#demos)):

<table>
  <tr>
    <td align="center" width="33%">
      <a href="https://qirabot.com/#demos"><img src="https://assets.qirabot.com/demos/afk_journey_tutorial.poster.webp" alt="Clear AFK Journey's tutorial and reach the open world"></a>
      <br><b>Clear AFK Journey's tutorial and reach the open world</b> — iOS real device
    </td>
    <td align="center" width="33%">
      <a href="https://qirabot.com/#demos"><img src="https://assets.qirabot.com/demos/lichess_play_chess.poster.webp" alt="Play chess on lichess.org"></a>
      <br><b>Play chess on lichess.org</b> — Android real device
    </td>
    <td align="center" width="33%">
      <a href="https://qirabot.com/#demos"><img src="https://assets.qirabot.com/demos/tile_match_game.poster.webp" alt="Beat a fruit tile-match game on its own"></a>
      <br><b>Beat a fruit tile-match game on its own</b> — Android real device
    </td>
  </tr>
</table>

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

Log in once — this opens your browser to authorize the CLI and saves an
API key locally (on a headless server, open the printed URL from any device;
`--paste` enters a key from your [dashboard](https://app.qirabot.com) manually):

```bash
qirabot login
```

Then hand the AI a task. Real, unedited output:

```text
$ qirabot browser "Search for SpaceX and get the first sentence of the article" --url wikipedia.org
Task: 6237d4ff-b96b-4c7d-addb-30d8a0334970
[1/20] type_text  ← "SpaceX"
        └ Type 'SpaceX' into the Wikipedia search bar and press enter to search.
Done: Space Exploration Technologies Corp., doing business as SpaceX, is an
      American spaceflight, telecommunications, and artificial intelligence
      company headquartered at the Starbase development site in Starbase, Texas.
```

Every run writes an HTML report with per-step screenshots; `--record`
captures a video of the whole run.

<!-- TODO: real-world CLI transcript section here, mirroring README.zh.md's
     "实战场景：社交媒体运营" (two runs sharing --user-data-dir: first pauses for
     the user to log in, second reuses the session unattended). Needs a real
     English-language run — do not translate the Chinese transcript. -->

## Python SDK

The CLI is powered by the same engine. Call `bot.ai()` from Python and the AI
likewise looks at the screen, decides the next action, and loops until the
task is done — except the result lands directly in your code:

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
`bot.extract(...)`, `bot.verify(...)` — with your code in control.

## Bolt onto your existing stack

No rewrite: pass your existing `page` / `driver` / device object and mix AI
steps with the selectors you already have. Add AI where selectors hurt —
visual assertions, dynamic widgets, and flows too tedious to script:

```python
import pytest
from qirabot import Qirabot

@pytest.fixture(scope="session")
def bot():
    with Qirabot(task_name="test-checkout") as bot:   # one task per run
        yield bot

def test_checkout(page, bot):     # `page` is your pytest-playwright fixture
    page.goto("https://shop.example.com")
    page.fill("#username", "test_user")             # your selectors, as-is
    page.click("#login-btn")

    # Visual assertion — survives markup rewrites and CSS refactors
    assert bot.verify(page, "the product grid shows items with prices and no error banner")

    # One line replaces a page of brittle selector steps
    result = bot.ai(page, "Complete checkout, name John Doe zip 10001", max_steps=8)
    assert result.success
```

Works the same for Selenium, Appium, pyautogui, and the built-in device
backends (`AdbDevice`, `WdaClient`, `Window`) — and anything else via a
7-primitive [custom adapter](https://qirabot.com/docs/backends/custom-adapters.html).

## Custom tools: let the AI call your code

Mid-task, the AI isn't limited to clicking and typing. `custom_tools`
registers plain Python functions the model can invoke as it works — hit an
internal API, query a database, fetch an OTP from your mail server, seed test
data, or pause for a human at a CAPTCHA. Name, description, and parameters are
introspected from the function itself:

```python
def gm_command(command: str) -> str:
    """Send a command to the game's GM backend and return its reply.
    Available commands: add_energy <amount>, add_gold <amount>"""
    return requests.post(GM_URL, json={"cmd": command}, timeout=10).text

result = bot.ai(
    device,
    "Complete every daily quest. If an out-of-energy popup appears, "
    "use gm_command to add 100 energy and continue",
    custom_tools=[gm_command],
)
```

The tool runs **locally on your machine** — the server never sees your
endpoints or credentials — and its return value becomes the model's next
observation. One instruction now spans systems that used to take a page of
glue code: UI steps, backend calls, and human handoffs in a single flow.
Details (schemas, error handling, pruning built-in tools):
[AI Tasks & Custom Tools](https://qirabot.com/docs/advanced/ai-tasks.html).
Runnable examples: [custom_tool_gm.py](examples/game/custom_tool_gm.py) ·
[06_human_in_the_loop.py](examples/automation/06_human_in_the_loop.py).

## Documentation

| Topic | |
|---|---|
| Getting started | [Installation](https://qirabot.com/docs/guide/installation.html) · [Quick Start](https://qirabot.com/docs/guide/quickstart.html) · [CLI Reference](https://qirabot.com/docs/guide/cli.html) |
| Platforms | [Browser](https://qirabot.com/docs/backends/browser.html) · [Android (adb, no Appium)](https://qirabot.com/docs/backends/android.html) · [iOS (WDA, no Appium)](https://qirabot.com/docs/backends/ios.html) · [Windows & Games (DirectInput)](https://qirabot.com/docs/backends/windows-games.html) · [Desktop](https://qirabot.com/docs/backends/desktop.html) · [Custom Adapters](https://qirabot.com/docs/backends/custom-adapters.html) |
| Integrations | [Playwright](https://qirabot.com/docs/frameworks/playwright.html) · [Selenium](https://qirabot.com/docs/frameworks/selenium.html) · [Appium](https://qirabot.com/docs/frameworks/appium.html) · [pytest](https://qirabot.com/docs/frameworks/pytest.html) |
| Advanced | [AI Tasks & Custom Tools](https://qirabot.com/docs/advanced/ai-tasks.html) · [Reports & Recording](https://qirabot.com/docs/advanced/reports.html) · [Configuration](https://qirabot.com/docs/advanced/configuration.html) · [Error Handling](https://qirabot.com/docs/advanced/error-handling.html) |
| Reference | [API — Actions & Platform Matrix](https://qirabot.com/docs/reference/api.html) |

## Examples

Runnable examples live in [examples/](examples/), in three styles:

- **Bolt onto your existing tests (pytest)** — [playwright/](examples/playwright/),
  [selenium/](examples/selenium/), [appium/](examples/appium/),
  [desktop/](examples/desktop/)
- **Standalone automation (plain scripts)** — scraping / RPA / agents:
  [automation/](examples/automation/)
- **Drive a game** — Windows desktop games (bind by HWND) and the iOS
  MMORPG script behind the [demo video](https://qirabot.com/#demos):
  [game/](examples/game/)

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
