---
title: Quick Start
description: Run your first AI-driven GUI automation in two commands, then the same task through the Python SDK — autonomous bot.ai() tasks and deterministic AI-located steps.
---

# Quick Start

Two commands — save your API key once (get it from your
[dashboard](https://app.qirabot.com)), then hand the AI a task:

```bash
qirabot login      # paste the key once; verified, stored, picked up by every later run
qirabot browser "Search for SpaceX and get the first sentence of the article" --url wikipedia.org
```

That's a complete run: the browser opens, the AI does the task, and the result
(plus an HTML report) lands in your terminal. All commands and options are in
the [CLI Reference](/guide/cli). (Prefer environment variables? `QIRA_API_KEY`
and a project `.env` still work and take precedence.)

## The same task in Python

`bot.ai()` is the same engine the CLI command runs: the AI looks at the
screen, decides the next action, and loops until the task is done:

```python
from qirabot import Qirabot

bot = Qirabot()
page = bot.open("https://www.wikipedia.org")

result = bot.ai(page, "Search for SpaceX and get the first sentence of the article")
print(f"Success: {result.success}")
print(f"Result: {result.output}")

bot.close()
```

## Deterministic steps

When you want to drive each step yourself instead of delegating the whole
task, the same natural-language targeting is available as single-step calls —
fast, low-cost, and under your control flow:

```python
from qirabot import Qirabot

bot = Qirabot()
page = bot.open("https://www.saucedemo.com")

# Describe each element in natural language (any language works);
# AI vision locates it, your code stays in control:
bot.type_text(page, "the Username field", "standard_user")
bot.type_text(page, "the Password field", "secret_sauce")
bot.click(page, "the Login button")

# Gate on visual state — wait_for polls until true, raises on timeout
bot.wait_for(page, "the Products page is shown")

# Pull structured data straight off the screen — no scraping, no selectors
count = bot.extract(page, "the number on the cart badge as an integer")

bot.close()
```

The core calls:

| Call | What it does |
|---|---|
| `bot.ai(target, task)` | Autonomous multi-step task — see, decide, act, loop until done |
| `bot.click(target, "desc")` | AI-located click (also `double_click`, `type_text`) |
| `bot.extract(target, "desc")` | Pull structured data from the screen |
| `bot.verify(target, "assertion")` | Visual assertion — returns `True`/`False`, never raises |
| `bot.wait_for(target, "condition")` | Poll until a visual condition holds, else raise |

## How a run ends

`result.success` is the pass/fail verdict; `result.status` says why:
`"completed"`, `"goal_failed"` (login wall, captcha), `"max_steps"` (budget
truncation — retry with more steps), or `"error"`.

```python
result = bot.ai(page, "Find the cheapest flight and hold it")
if result.status == "max_steps":
    # not a real failure — the budget was too small; retry with headroom
    result = bot.ai(page, "Find the cheapest flight and hold it", max_steps=50)
```

## Reports

Every run writes a self-contained HTML report with per-step screenshots to
`./qira_runs/<date>/<time-id>/` — including on error or Ctrl+C, so you can see
where it stopped. Pass `record=True` (or `--record` on the CLI) to also
capture a video of the run.

## Next steps

- Pick your backend: [Browser](/backends/browser) ·
  [Android](/backends/android) · [iOS](/backends/ios) ·
  [Windows & Games](/backends/windows-games) · [Desktop](/backends/desktop)
- Bolting onto an existing Playwright / Selenium / Appium suite? See
  [Custom Adapters & Bolt-On](/backends/custom-adapters)
- [CLI Reference](/guide/cli)
