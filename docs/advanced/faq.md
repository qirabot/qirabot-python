---
title: FAQ — Common Questions about Qirabot
description: Do you need your own model API key, which calls are billed, why recordings come out black, headless fallback, long waits between steps, and other frequently asked questions.
---

# FAQ

## Do I need my own model API key (OpenAI, Anthropic, …)?

No. The vision models are hosted on Qirabot's servers — run `qirabot login`
once (browser authorization) and every run works. There are no model endpoints
or env-var matrices to configure; you pick a quality tier per call or per bot
with a [model alias](/advanced/configuration#model-language) (`fast` ·
`balanced` · `balanced_pro` · `high_quality`).

## Which calls are billed, and which are free?

Calls that invoke the AI are billed: `ai()`, `extract`, `verify`, `wait_for`,
and the AI-located actions (`click`, `type_text`, `double_click` with an
element description). Direct actions never touch the AI and are free:
`navigate`, `go_back`, `close_tab`, `scroll`, `press_key`, `screenshot`,
`launch_app`, `type_text` with an empty locate, and `mouse_up` without a
locate. The [API reference](/reference/api) marks these "no AI, no billing".
Your balance lives in the [dashboard](https://app.qirabot.com); running dry
raises `InsufficientBalanceError`.

## What data leaves my machine?

Screenshots, your instruction text, and step metadata — nothing else. Code,
cookies, and credentials stay local; actions execute on your machine. Full
details in [Data & Privacy](/reference/privacy).

## Why is my recording black?

- **Windows, `record_window=True`**: `gdigrab` produces black frames for
  minimized or GPU-composited (fullscreen-exclusive game) windows — keep the
  window visible, or record the full screen for games.
- **macOS**: grant your terminal/IDE the "Screen Recording" permission.

Recording is best-effort: a missing ffmpeg or denied permission warns and
never fails the task — check `recording.ffmpeg.log` in the run dir. See
[Reports & Recording](/advanced/reports).

## Why did the browser start headless?

On a display-less box (no `DISPLAY`), `bot.open()` and the CLI automatically
fall back to headless, with a warning. Pass `--headless` explicitly to make
it unconditional.

## I got `MissingDependencyError` — what now?

An optional backend dependency isn't installed. The error message contains
the exact `pip install "qirabot[<extra>]"` to run; the extras are listed in
[Installation](/guide/installation).

## My script sleeps between steps — will the task time out?

No. The SDK sends a background heartbeat while your process is alive, so
long waits between `bot.*` calls are safe. Only a silently-dead process is
reclaimed, by the server's orphan cleaner after ~5 minutes. Details in
[Configuration](/advanced/configuration#task-lifecycle).

## Can I type Chinese or emoji on Android?

Yes — `bot.type_text(...)` works out of the box. Text beyond ASCII goes
through the bundled ADBKeyboard IME, installed on demand and switched back
afterwards. See [Android](/backends/android).

## Do I have to rewrite my Playwright / Selenium / Appium suite?

No. Pass your existing `page` or `driver` as the target and add AI steps
only where selectors hurt — see the integration guides for
[Playwright](/frameworks/playwright), [Selenium](/frameworks/selenium),
[Appium](/frameworks/appium), and [pytest](/frameworks/pytest).

## I'm coming from Airtest / qirabot 1.x

The built-in device backends are drop-in replacements
(`connect_device(...)` → `AdbDevice` / `WdaClient` / `Window`), and a
reference adapter keeps old scripts running unchanged. See
[Migrating from Airtest](/backends/custom-adapters#migrating-from-airtest-qirabot-1-x).
