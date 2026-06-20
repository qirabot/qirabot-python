# Qirabot API reference (condensed)

Quick reference for the skill. The SDK README is the full source of truth; this
mirrors the parts an agent needs to write a script. Keep in sync with the SDK.

## Construct

```python
from qirabot import Qirabot
bot = Qirabot()                       # reads QIRA_API_KEY from env
```

Common constructor options (all keyword):

| Option | Default | Notes |
|---|---|---|
| `api_key` / env `QIRA_API_KEY` | — | auth |
| `base_url` / env `QIRA_BASE_URL` | `https://app.qirabot.com` | self-hosted/regional |
| `model_alias` | `""` | `fast` \| `balanced` \| `balanced_pro` \| `high_quality` |
| `language` | `""` | response language tag, e.g. `"zh"`, `"en"` |
| `task_name` | `""` | shown in dashboard / report |
| `report` | `True` | write HTML report on close |
| `report_dir` / env `QIRA_REPORT_DIR` | `./qira_runs/<date>/<run>/` | output root |
| `record` / env `QIRA_RECORD` | `False` | ffmpeg screen recording into the report |
| `screenshot_annotate` | `True` | red crosshair at click/type point |
| `retry` / `retry_delay` | `1` / `1.0` | per-action retry on transient failure |
| `settle_seconds` / env `QIRA_SETTLE_SECONDS` | per-platform | fixed pause after each action |

## Default: hand the task to `bot.ai`

```python
result = bot.ai(target, instruction, max_steps=20, *, on_step=None, model_alias="", language="")
# result.success -> bool, result.output -> str (final answer)
```

Runs the full perceive → decide → act loop on qirabot's backend (step history
managed server-side; self-heals on a misfire). `on_step(step)` fires after each
step; `StepResult` has `.step`, `.action_type`, `.params`, `.finished`.

Prefer this over hand-sequencing primitives. Drop to the primitives below only
for strict determinism or a stable flow you'll run repeatedly (e.g. CI).

## Bind (drop the repeated first arg)

Every action's first argument is the framework object (`page`/`driver`/device).
For a single stable target, `bind()` once:

```python
bot = Qirabot().bind(driver)   # Selenium/Appium driver, pyautogui, Airtest G/device
bot.ai("complete the task")    # no target arg
bot.click("Login")
bot.current_page()             # reach the live page from a bound proxy
```

Recommended for Airtest / pyautogui / Appium / Selenium. For **Playwright keep
the explicit form** `page = bot.click(page, ...)` so new-tab follows stay visible.

## AI-located actions (one model call each)

```python
bot.click(target, locate, *, timeout=0.0, interval=2.0, wait="", model_alias="", language="")
bot.type_text(target, locate, text, *, press_enter=False, clear_before_typing=False, timeout=0.0, ...)
bot.double_click(target, locate, ...)
```

- `locate` is a natural-language description ("the blue Submit button").
- `timeout>0` auto-waits (polls a visual assertion) until present, else raises
  `QirabotTimeoutError`. `wait="..."` overrides the derived assertion.
- Return the current target; if a click opened a **new tab**, that tab is
  returned — reassign: `page = bot.click(page, ...)`.

## AI checks (cheap — use even after `bot.ai`)

```python
text = bot.extract(target, instruction, *, language="")   # -> str
ok   = bot.verify(target, assertion)                       # -> bool, never raises
bot.wait_for(target, assertion, timeout=30.0, interval=2.0)# gate, raises on timeout
```

Honesty note: `verify`/`wait_for` poll an assertion (truthful). Prefer
`wait_for(assertion)` + `click(...)` over relying on a click to "find" something
that may not exist.

`extract()` reads what's **visible on screen** — it cannot return values that
live only in the DOM/attributes (a link's `href`, a `data-*`, an `input`'s real
value). For those, drop to the live driver via `bot.current_page(target)` (a real
Playwright `Page`, even with the explicit-target form) and read it deterministically:

```python
pg = bot.current_page(page)
urls = pg.eval_on_selector_all("a[href*='/video/']", "els => els.map(e => e.href)")
```

Also beware **ambiguous locates**: `extract(target, "the logged-in username")`
can grab a rotating search-box hint instead of the real value — scope the phrase
and cross-check against a screenshot.

**Human-in-the-loop waits** (QR scan, OTP, captcha — possibly minutes): each
`wait_for`/`verify` poll is a *billed* AI call, so the default `interval=2.0`
burns credits while a human acts. Raise the interval (e.g. `interval=8.0`) or
skip the AI and poll the live driver for free, e.g.
`bot.current_page(target).wait_for_url("**/success**")` or watch
`...context.cookies()`.

## Non-AI actions (no model call)

```python
page = bot.open(url="", headless=False, *, viewport=(1280,800), user_data_dir="", channel="", cdp_url="")
bot.navigate(target, "example.com")     # scheme optional
bot.go_back(target)                     # Playwright: smart (closes a historyless new tab)
page = bot.close_tab(page)              # Playwright only
bot.scroll(target, "down", 3)          # or distance=, x=, y=
page = bot.press_key(target, "Enter")  # "ctrl+c", "ctrl+t" (reassign on tab switch)
path = bot.screenshot(target)          # saved frame -> path (None if report=False)
bot.launch_app("WeChat")               # desktop: open an app (pyautogui can't)
```

### Persistent login — reuse a session across runs

A run is one session; login state is lost when it ends (see Lifecycle). To keep
cookies/login **between** runs, open with a persistent Chromium profile:

```python
page = bot.open(url, user_data_dir="~/.qira-profiles/<site>")
if not bot.verify(page, "the user is logged in (avatar shown, no Login button)"):
    ...  # first run only: do the login (e.g. QR scan), then it sticks
```

The first run authenticates (scan / type credentials); later runs reuse the same
profile already logged in, so they skip straight to the task. This is the
intended pattern for any auth-gated automation.

## Platform support (summary)

AI-located actions (`click`/`type_text`/`double_click`) and AI ops
(`extract`/`verify`/`wait_for`/`ai`) work on **every** framework. Lower-level
actions vary:

- `navigate`/`close_tab`: browser only (`close_tab` = Playwright only).
- `go_back`: Playwright/Selenium/Appium; Airtest = Android only; pyautogui = no.
- `long_press`: Appium/Airtest mobile only.
- `right_click`/`hover`: full on browser/desktop; mobile taps / no-ops.

Unsupported actions raise `NotImplementedError`.

## Lifecycle

```python
with Qirabot(task_name="job") as bot:   # auto-close + report on exit
    ...
# or: bot.close()  (atexit also cleans up; server times out orphans after 30 min)
```

## Errors

```python
from qirabot import (QirabotError, AuthenticationError, InsufficientBalanceError,
                     QirabotTimeoutError, ActionError, RateLimitError, QirabotConnectionError)
```

`QirabotError` is the base; catch it last.
