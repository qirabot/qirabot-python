---
title: Configuration
description: Every Qirabot knob - API key resolution order, constructor options, environment variables, model aliases and per-call overrides, response language, and settle delay tuning.
---

# Configuration

If you ran `qirabot login`, you're already configured — the SDK reads the
same saved key:

```python
from qirabot import Qirabot

bot = Qirabot()  # api_key param > QIRA_API_KEY env var > `qirabot login` config
```

An environment variable always wins over the login config (so CI and one-off
overrides behave as expected). Settings can also live in a project `.env`:
scripts opt in explicitly — `from qirabot import load_dotenv; load_dotenv()`
— which reads `$QIRA_DOTENV` or `./.env` and never overrides exported
variables. The CLI loads `.env` automatically; the SDK never reads it on its
own.

## Constructor options

| Parameter | Env Variable | Default | Description |
|---|---|---|---|
| `api_key` | `QIRA_API_KEY` | `qirabot login` config | API key |
| `base_url` | `QIRA_BASE_URL` | `https://app.qirabot.com` | API server URL |
| `timeout` | — | `120.0` | HTTP request timeout (seconds) |
| `verify_ssl` | — | `True` | TLS verification (set `False` for self-hosted / self-signed) |
| `model_alias` | — | `balanced_pro` | Model alias for all operations; `""` = server default |
| `language` | — | server default | Response language, e.g. `"zh"` / `"en"` |
| `task_name` | — | `""` | Task name (visible in dashboard) |
| `report` | — | `True` | Write an HTML run report on close |
| `report_dir` | `QIRA_REPORT_DIR` | `./qira_runs/...` | Report output root |
| `record` | `QIRA_RECORD` | `False` | Record the screen (ffmpeg) |
| `record_fps` | — | `12` | Recording frame rate |
| `record_window` | `QIRA_RECORD_WINDOW` | `False` | Windows: record just the window under test |
| `record_audio` | `QIRA_RECORD_AUDIO` | `False` | Windows: capture system audio |
| `record_audio_offset` | `QIRA_AUDIO_OFFSET` | `None` | A/V sync offset in seconds |
| `record_device` | `QIRA_RECORD_DEVICE` | `False` | Record the device screen (adb / Appium) |
| `record_mjpeg_url` | `QIRA_RECORD_MJPEG_URL` | `None` | Record an MJPEG stream (iOS WDA) |
| `screenshot_annotate` | — | `True` | Red crosshair at click/type coordinates |
| `screenshot_format` | — | `"jpeg"` | `"jpeg"` or `"png"` |
| `screenshot_quality` | — | `80` | JPEG quality, 1–100 |
| `retry` | — | `1` | Retries per action on transient failures |
| `retry_delay` | — | `1.0` | Seconds between retries |
| `settle_seconds` | `QIRA_SETTLE_SECONDS` | per-platform | Pause after each action before the next screenshot |

## Model & language

`model_alias` selects which model backs every operation:

| Alias | Trade-off |
|---|---|
| `fast` | Cheapest, lowest latency |
| `balanced` | Good cost/quality balance |
| `balanced_pro` | The default — stronger than `balanced` |
| `high_quality` | Best quality, highest cost |

```python
bot = Qirabot(model_alias="high_quality")        # applies to all actions
bot.click(page, "Login", model_alias="fast")     # or override per call
```

Check your [dashboard](https://app.qirabot.com) for the live list your
account can use; leave it empty for the server default.

`language` sets the language of AI responses (extracted text, reasoning) —
a short tag like `"zh"` or `"en"`:

```python
bot = Qirabot(language="zh")
text = bot.extract(page, "Get the main heading", language="zh")
```

## Settle delay

After every screen-changing action each adapter pauses briefly so the UI
repaints before the next screenshot — without it the model can capture a
mid-animation frame and wrongly conclude the action did nothing. Defaults
are tuned per platform (desktop/Android `1.0`s, Appium/WDA `0.6`s;
Playwright relies on its own auto-waiting and adds none).

```python
bot = Qirabot(settle_seconds=1.5)   # laggy remote device: wait longer
bot = Qirabot(settle_seconds=0.3)   # fast local app: go quicker
bot = Qirabot(settle_seconds=0)     # disable; lean on wait_for() instead
```

This is a blunt fixed delay. For "wait until X appears" prefer the auto-wait
`timeout=` / `wait_for()` polling — it returns as soon as the condition
holds.

## Task lifecycle

Each `Qirabot` instance manages a server-side task: created on construction
(pass an existing `task_id` to attach instead), every call recorded as a
step, marked complete on `close()` / context-manager exit. If `close()` is
never called, `atexit` cleans up, and the server times out orphaned SDK
tasks after 30 minutes.
