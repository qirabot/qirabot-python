---
title: CLI Reference
description: Run natural-language GUI automation tasks from the command line — browser, Android, iOS, and desktop subcommands, recording, reports, and script-friendly exit codes.
---

# CLI Reference

The `qirabot` command runs a task end-to-end without writing Python. It ships
in the core package. `android`, `ios`, and `desktop --window-title/--hwnd` run
on the built-in backends — no extras. Only `browser` (`qirabot[browser]`),
whole-screen `desktop` (`qirabot[desktop]`), and the Appium engine
(`qirabot[appium]`) need one.

```bash
# Browser (needs qirabot[browser] + `playwright install chromium`)
qirabot browser "Search for SpaceX and get the first sentence of the article" --url wikipedia.org

# Browser — headless/viewport; a persistent profile; or take over a running Chrome via CDP
qirabot browser "..." --headless --viewport 1920x1080
qirabot browser "..." --user-data-dir ~/.qira-profile --channel chrome
qirabot browser "..." --cdp-url http://localhost:9222

# Android — direct over adb (built in; only needs the adb binary, no server)
qirabot android "Open settings and turn on airplane mode"
qirabot android "..." -d emulator-5554 --app-package com.android.settings

# iOS — direct to WebDriverAgent (built in; WDA must be running on :8100)
qirabot ios "Send hi to Alice on WeChat" --bundle-id com.tencent.xin

# Either can go through an Appium server instead (needs qirabot[appium])
qirabot android "..." --appium-url http://localhost:4723
qirabot ios "..." --device "iPhone 15"   # simulators only (selects Appium)

# Desktop via pyautogui (needs qirabot[desktop])
qirabot desktop "Create a new note titled Groceries" --app Notes

# Desktop bound to ONE Windows window (built in) — DirectInput scancode input
qirabot desktop "Open the inventory and list all items" --window-title "Genshin"
qirabot desktop "..." --hwnd 132456

# Mount domain knowledge for the run — game rules, business terms (32KB total)
qirabot browser "Buy 10 stamina potions in the shop" -k game-rules.md -k gm-policy.md

# Environment check — what's installed, what's missing, is the server reachable
qirabot doctor

# Read-only server queries
qirabot task <task_id>            # status, commands, steps
qirabot screenshot <task_id>      # download a screenshot
qirabot models                    # list model aliases
```

## Commands

| Command | Purpose |
|---|---|
| `browser INSTRUCTION` | Run an AI task in a local browser ([Browser backend](/backends/browser)) |
| `android INSTRUCTION` | Run an AI task on an Android device ([adb direct](/backends/android), built in; `--appium-url` for Appium) |
| `ios INSTRUCTION` | Run an AI task on an iOS device ([WDA direct](/backends/ios), built in; `--appium-url`/`--device` for Appium) |
| `desktop INSTRUCTION` | Run an AI task on the [desktop screen](/backends/desktop) (pyautogui; `--window-title`/`--hwnd` binds [one Windows window](/backends/windows-games), built in) |
| `login` | Log in via the browser and save the API key (`--paste` for manual entry, `--status` shows the active key, masked) |
| `install-browser` | One-time Chromium download for the browser backend |
| `open-browser` | Open a browser to log in to sites by hand — the session persists in `--user-data-dir`, no API key needed |
| `doctor` | Check Python, API key/server, and per-backend dependencies |
| `task TASK_ID` | Print a task's status, commands, and steps |
| `screenshot TASK_ID` | Download a task screenshot |
| `models` | List available model aliases |

## Global options

Global options go **before** the subcommand (they configure the connection):

```bash
qirabot --api-key qk_... --base-url https://app.qirabot.com browser "..."
```

The API key resolves in this order: `--api-key` flag > `QIRA_API_KEY` env var
> project `.env` > the `qirabot login` config file. `qirabot login --status`
shows which layer is active. Also available: `--timeout`,
`--verify-ssl` / `--no-verify-ssl`, `--version`.

## Exit codes

Script-friendly: `0` task succeeded, `1` task failed or any error, `130`
interrupted with Ctrl+C — so `qirabot browser "..." && next-step` only
proceeds on success.

## Shared run options

`browser` / `android` / `ios` / `desktop` all take:

| Option | Default | What it does |
|---|---|---|
| `-n, --name` | derived from the instruction | Task name shown in the web UI |
| `-m, --model` | server default | Model alias (see [Configuration](/advanced/configuration)) |
| `-l, --language` | server default | Response language, e.g. `zh`, `en` |
| `--max-steps` | `20` | Step budget for the AI task |
| `-k, --knowledge` | — | Knowledge file the AI consults during the task (UTF-8 text; repeatable, 32KB total). Same rules as `bot.ai(knowledge=...)`: files only, no URLs — fetch remote sources yourself first |
| `--report / --no-report` | on | Write an HTML run report |
| `--report-dir` | `./qira_runs/...` | Report output root (env `QIRA_REPORT_DIR`) |
| `--annotate / --no-annotate` | on | Crosshair click/type coordinates on saved screenshots |
| `--record` | off | Record the run to `recording.mp4` (see below) |

## Per-command options

**`browser`** — see the [Browser backend](/backends/browser):

| Option | Default | What it does |
|---|---|---|
| `-u, --url` | — | URL to open (AI navigates if omitted) |
| `--headless` | off | Headless mode (auto-on when there's no display) |
| `--viewport` | `1280x800` | Viewport as `WIDTHxHEIGHT` |
| `--channel` | bundled Chromium | Use an installed browser: `chrome`, `msedge`, … |
| `--user-data-dir` | — | Persistent profile dir (cookies/logins survive runs) |
| `--browser-arg` | — | Extra Chromium launch arg, repeatable |
| `--cdp-url` | — | Attach to a running Chrome via CDP; mutually exclusive with the four options above |

**`android`** — see the [Android backend](/backends/android):

| Option | Default | What it does |
|---|---|---|
| `-d, --device` | the only connected device | adb serial from `adb devices` |
| `--app-package` | — | App package to launch (e.g. `com.android.settings`) |
| `--app-activity` | — | App activity to launch |
| `--appium-url` | direct adb, no server | Passing it switches to the [Appium engine](/frameworks/appium) |
| `--record` | off | Record the **device** screen (adb screenrecord / Appium API) |

**`ios`** — see the [iOS backend](/backends/ios):

| Option | Default | What it does |
|---|---|---|
| `--wda-url` | `http://127.0.0.1:8100` | WebDriverAgent URL — this selects the device (USB real device: `iproxy 8100 8100`) |
| `--bundle-id` | — | App bundle id to launch (e.g. `com.tencent.xin`) |
| `--device` | — | Simulator device type from `xcrun simctl list devicetypes` — switches to the Appium engine, simulators only (no `-d` short: switching engines is deliberate) |
| `--appium-url` | direct WDA, no server | Appium server URL (with `--device`) |
| `--record` | off | Record the **device** screen (WDA MJPEG + ffmpeg / Appium API) |
| `--mjpeg-url` | `--wda-url` host on port 9100 | MJPEG stream override for `--record` |

**`desktop`** — see [Desktop](/backends/desktop) and
[Windows & Games](/backends/windows-games):

| Option | Default | What it does |
|---|---|---|
| `--app` | — | Launch/activate an app first (macOS: name or bundle id; Windows: exe/registered name/UWP id; Linux: executable) |
| `--app-wait` | `2.0` | Seconds to wait for the window after `--app` |
| `--window-title` | — | Bind to the window matching this title regex (Windows window backend) |
| `--hwnd` | — | Bind to a window handle, decimal (Windows window backend) |

**`screenshot TASK_ID`** — `-s/--step` (0 = latest), `-o/--output`,
`-f/--force` (overwrite).

`--record` saves `recording.mp4` into the run dir and embeds it in the HTML
report. What gets recorded differs per target:

- `browser` / `desktop` — the **host** screen via ffmpeg (needs ffmpeg on
  PATH). With a window bound (`--window-title`/`--hwnd`), the recording
  follows that window.
- `android` — the **device** screen: `adb screenrecord` on the default engine,
  or Appium's recording API on the Appium engine.
- `ios` — the **device** screen: WDA's MJPEG stream on the default engine
  (needs ffmpeg; USB real device also needs `iproxy 9100 9100`), or Appium's
  recording API on the Appium engine.

Recording mechanics, report layout, and audio capture are covered in
[Reports & Recording](/advanced/reports). Runs honor the same env vars as
the SDK — `QIRA_REPORT_DIR`, `QIRA_SETTLE_SECONDS`, `QIRA_RECORD*`, etc.;
the full list is in [Configuration](/advanced/configuration).
