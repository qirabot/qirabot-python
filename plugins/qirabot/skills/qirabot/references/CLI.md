# Qirabot CLI reference (condensed)

The `qirabot` command ships with the package (any install/extra). Same auth as
the SDK: `QIRA_API_KEY` from the environment or `./.env` (the CLI loads `.env`
automatically). One run command = one server task = one `ai()` run — there is
no CLI equivalent of `extract`/`verify`/`wait_for` or of chaining several
`ai()` calls in one session; those need the SDK.

## Global options — go BEFORE the subcommand

```bash
qirabot --base-url https://self.hosted browser "..."   # right
qirabot browser "..." --base-url https://self.hosted   # wrong (unknown option)
```

| Option | Default | Notes |
|---|---|---|
| `--api-key` | env `QIRA_API_KEY` | auth |
| `--base-url` | env `QIRA_BASE_URL`, else `https://app.qirabot.com` | self-hosted/regional |
| `--timeout` | `120` | HTTP timeout (seconds) |
| `--verify-ssl/--no-verify-ssl` | verify | TLS verification |

`-h/--help` works everywhere and prints each option's default; `--version`
prints the package version.

## Run commands: `browser` / `android` / `ios` / `desktop`

All four take the instruction as the positional argument and share:

| Option | Default | Notes |
|---|---|---|
| `-n/--name` | derived from the instruction (first line, ≤60 chars) | task name in the web UI |
| `-m/--model` | server default | model alias — list them with `qirabot models` |
| `-l/--language` | server default | e.g. `zh`, `en` |
| `--max-steps` | `20` | AI step budget |
| `--report/--no-report` | report | HTML run report |
| `--report-dir` | env `QIRA_REPORT_DIR`, else `./qira_runs/<date>/<run>/` | output root |
| `--annotate/--no-annotate` | annotate | crosshair on saved screenshots |
| `--record` | off | see per-command semantics below — host screen on browser/desktop, **device** screen on android/ios |

**Exit codes** (CI-gateable): `0` = model achieved the goal · `1` = failed /
error / max-steps exhausted · `130` = Ctrl+C (task recorded as *cancelled*
server-side, not failed). Live per-step trace prints to stdout while running
(`[3/20] click "Login" └ reasoning…`), final line is `Done: <output>` or
`Failed: <output>`.

### `qirabot browser "<instruction>"`

| Option | Notes |
|---|---|
| `-u/--url` | start URL (scheme optional). Omit and the AI navigates itself — then name the site in the instruction. |
| `--headless` | headless Chromium. On display-less Linux a headed launch auto-falls-back to headless anyway. |
| `--viewport` | `1280x800` |
| `--channel` | `chrome` / `msedge` — use the installed browser instead of bundled Chromium |
| `--user-data-dir` | persistent profile → login survives across runs (pass an absolute path) |
| `--browser-arg` | extra Chromium arg, repeatable |
| `--cdp-url` | attach to a running Chrome (`http://localhost:9222` or a Browserless/Browserbase `wss://`). Mutually exclusive with `--headless/--user-data-dir/--channel/--browser-arg`. |

`--record` = host screen via ffmpeg (needs ffmpeg on PATH).

### `qirabot android "<instruction>"`

Two engines; default `airtest` drives the device straight over adb, no server:

```bash
qirabot android "Open settings"                    # the only adb device
qirabot android "..." -d emulator-5554             # pick one of several
qirabot android "..." --app-package com.android.settings --app-activity .Settings
qirabot android "..." --engine appium -d emulator-5554   # via Appium server
```

| Option | Notes |
|---|---|
| `--engine` | `airtest` (default, adb direct) \| `appium` (needs a running server) |
| `-d/--device` | adb serial; optional with exactly one device. Appium engine: passed as `deviceName`. |
| `--app-package` / `--app-activity` | app to launch first |
| `--appium-url` | `http://localhost:4723` — **appium engine only** (usage error otherwise) |

`--record` = **device** screen on both engines (airtest: adb screenrecord;
appium: Appium's recording API).

### `qirabot ios "<instruction>"`

Default engine `airtest` talks to WebDriverAgent directly — WDA must already be
running (USB real device: `iproxy 8100 8100` first). Appium engine for
simulators or auto WDA build/sign:

```bash
qirabot ios "..." --bundle-id com.tencent.xin           # WDA on 127.0.0.1:8100
qirabot ios "..." --wda-url http://192.168.1.20:8100    # another device's WDA
qirabot ios "..." --engine appium -d "iPhone 15" --bundle-id com.apple.Preferences
```

| Option | Notes |
|---|---|
| `--engine` | `airtest` (default, direct WDA) \| `appium` |
| `--wda-url` | `http://127.0.0.1:8100` — how the default engine picks the device. **airtest engine only.** |
| `--bundle-id` | app to launch (via WDA `app_launch`, iOS 17+-safe) |
| `-d/--device` | **appium engine only**: a simulator device type from `xcrun simctl list devicetypes` — not a real device's name |
| `--appium-url` | `http://localhost:4723` — **appium engine only** |
| `--mjpeg-url` | WDA MJPEG stream for `--record` (default: `--wda-url` host on port 9100). **airtest engine + `--record` only.** |

`--record` = **device** screen. Airtest engine transcodes WDA's MJPEG stream
(needs ffmpeg; USB real device also needs `iproxy 9100 9100` — probed up front,
fails fast with the fix). Appium engine uses Appium's recording API, no extra
setup. Engine-mismatched flags are hard usage errors, not ignored.

### `qirabot desktop "<instruction>"`

Whole primary screen via pyautogui (any OS).

| Option | Notes |
|---|---|
| `--app` | launch/activate an app first. macOS: app name or bundle id; Windows: exe path / registered name / UWP AppUserModelID; Linux: executable |
| `--app-wait` | `2.0` — seconds to wait for the window after `--app` |

`--record` = host screen via ffmpeg.

## Utility commands (useful on the SDK path too)

| Command | What it does |
|---|---|
| `qirabot doctor` | Environment check: Python, API key + server reachability, each backend's deps, ffmpeg. Exit `0` when at least one backend can run end-to-end — gate setup scripts/CI on it. |
| `qirabot task <task_id>` | Server-side status + commands + steps tables for any task (CLI- or SDK-created). |
| `qirabot screenshot <task_id> [-s N] [-o PATH] [-f]` | Download a task screenshot (`-s 0` = latest step). Refuses to overwrite without `-f`. |
| `qirabot models` | List available model aliases — the valid `-m` values. |

## When the CLI is the wrong tool → use the SDK

- The script must **branch or read values**: no `extract`/`verify`/`wait_for`.
- **Several `ai()` calls / mixed primitives** in one session: the CLI is one
  instruction per invocation, and device state does not survive across runs.
- **Custom targets**: your own Selenium driver / an already-built Appium
  session / an airtest Windows window — `bind()` is SDK-only.
- **Machine-parsing the result**: output is rich-formatted for humans
  (`Done: <output>`); there is no `--json` mode. Parse the exit code only.
