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
| `browser INSTRUCTION` | Run an AI task in a local browser (Playwright) |
| `android INSTRUCTION` | Run an AI task on an Android device (adb direct, built in; `--appium-url` for Appium) |
| `ios INSTRUCTION` | Run an AI task on an iOS device (WDA direct, built in; `--appium-url`/`--device` for Appium) |
| `desktop INSTRUCTION` | Run an AI task on the desktop screen (pyautogui; `--window-title`/`--hwnd` binds one Windows window, built in) |
| `login` | Save your API key once (`--status` shows the active key, masked) |
| `install-browser` | One-time Chromium download for the browser backend |
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

`browser` / `android` / `ios` / `desktop` all take: `-n/--name`, `-m/--model`,
`-l/--language`, `--max-steps`, `--report/--no-report`, `--report-dir`,
`--annotate/--no-annotate`, and `--record`.

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

Runs honor the same env vars as the SDK — `QIRA_REPORT_DIR`,
`QIRA_SETTLE_SECONDS`, `QIRA_RECORD*`, etc.
