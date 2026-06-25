---
name: qirabot
description: "Drive any GUI with natural language — click, type, extract, and verify on web browsers, Android, iOS, desktop apps, and games — using the Qirabot Python SDK. Use this when the user wants to automate, test, or scrape a user interface by describing elements in plain language instead of CSS/XPath selectors; when driving a mobile app or a native desktop/game where DOM-based tools don't work; or for visual UI verification, screenshots, and RPA. Triggers include: automate a website or app, UI/end-to-end test, fill a form, scrape a page, tap or click a button, verify what's on screen, drive an Android/iOS app, automate a desktop application."
license: MIT
metadata:
  author: qirabot
---

## Step 0 — Preflight (always run first)

Do NOT write an automation script before the environment checks out. Run:

```bash
python scripts/preflight.py browser     # or: android | ios | desktop
```

It verifies Python version, `QIRA_API_KEY`, that `qirabot` is importable, and
target-specific bits (e.g. `adb devices`). **If it fails, stop and fix what it
prints** — don't proceed and debug a half-set-up run.

**One interpreter, one source of truth.** Preflight validates *one* Python and,
on success, prints its absolute path (`interpreter: ...` and a run line). Run
your script with **that exact path**, never a bare `python` — otherwise the run
can drift to a different env than the one you just checked (the #1 false-"Ready"
trap). Whatever already works (an existing venv, the user's global) is fine — the
point is to *reuse the validated one*, not to force a new venv.

Bootstrap only when preflight reports something missing. Prefer an isolated venv
over the user's global Python (and **re-run preflight with that venv's Python**
so it becomes the validated interpreter):

```bash
# browser / iOS / desktop can share one venv:
python3 -m venv .qira-venv && source .qira-venv/bin/activate   # Windows: .qira-venv\Scripts\activate
pip install "qirabot[browser]"      # → also: playwright install chromium
#   or  qirabot[appium]  (iOS: + Appium server & WebDriverAgent)  /  qirabot[desktop]

# the airtest backends (Android, iOS, and window-scoped Windows desktop) need
# their OWN venv on Python 3.10-3.12 — airtest pins numpy<2 and would conflict a
# shared env:
python3.12 -m venv .qira-venv-airtest && source .qira-venv-airtest/bin/activate
pip install "qirabot[airtest]"

export QIRA_API_KEY="qk_..."        # from https://app.qirabot.com
```

## Step 1 — Pick a target and start from a template

| Target | Template | Extra |
|---|---|---|
| Web browser (Qirabot launches Chromium) | `templates/browser.py` | `qirabot[browser]` + `playwright install chromium`. Also supports connecting to an existing Chrome via `cdp_url` (e.g. Browserless/Browserbase). |
| Android / iOS — Airtest (no Appium server, fastest start) | `templates/android.py` (Android starter; for iOS keep the API, swap the `connect_device` string) | `qirabot[airtest]` (Python 3.10-3.12) |
| Android / iOS via Appium, or any Selenium driver (you build the driver, then `bind()`) | `templates/bolt_on.py` | `qirabot[appium]` / `qirabot` + `selenium` |
| Desktop — Windows & macOS (`bind()` your driver) | `templates/bolt_on.py` | `qirabot[desktop]` (whole screen, any OS) · `qirabot[airtest]` (Windows only, one window) |

Copy the template, fill in the `TODO`s (start URL / app package, and the task),
then run it with **the interpreter preflight echoed** (its absolute path), not a
bare `python`. `templates/bolt_on.py` shows the bind-an-existing-driver pattern
with Selenium as the runnable example plus Appium (iOS/Android), pyautogui
(whole-screen desktop, any OS), and Airtest (window-scoped Windows desktop)
variants in comments; see `references/REFERENCE.md` for the full per-platform
action matrix and `bind()` details.

## Step 2 — Hand the task to qirabot (default), drop to primitives only to optimize

**Default: give the whole task to `bot.ai`.**

```python
from qirabot import StepResult

def on_step(step: StepResult) -> None:   # live trace -> stdout (see below)
    label = "done" if step.finished else step.action_type
    print(f"  step {step.step}: {label} {step.params} — {step.decision}")

result = bot.ai(target, "Add the cheapest item to the cart and check out",
                max_steps=15, on_step=on_step)
print(result.success, result.output)
```

`bot.ai` offloads the perceive → decide → act loop to qirabot, which manages its
own step history and self-heals when a step misfires.

**Keep the task string a concise goal, not a step-by-step script.** `bot.ai` is
smart enough to plan its own clicks — over-specifying ("click Search, then type
X, then click the first result, then…") fights the model, locks in a brittle
path, and burns extra steps. Write what success looks like, not how to get
there. Good: `"Add the cheapest in-stock item to the cart and check out"`.
Bad: a 6-step click-by-click recipe.

The examples here pass the target explicitly (`bot.ai(target, ...)`). **If you
`bind()` a stable target first** — as the `android.py` and `bolt_on.py` templates
do — drop the leading arg: `bot.ai("...")`, `bot.click("...")`. (Keep the explicit
form for Playwright so new-tab follows stay visible — see `references/REFERENCE.md`.)

**Always pass `on_step`.** Until it returns, `bot.ai` is a black box — `result`
only lands at the end. `on_step` fires after every step and prints the model's
running `decision` + action to stdout, which is your one live window into the
run: a stuck, looping, or failed run becomes debuggable straight from the
console, without opening the HTML report. (`StepResult` also carries `.output`
and token/duration counts — see `references/REFERENCE.md`.)

**Drop to the per-step primitives only as a deliberate optimization** — when you
want strict, reproducible determinism, or you're codifying a stable flow to run
repeatedly (e.g. a CI regression check). They cost less per action and are
reproducible, but are brittle to UI changes:

```python
bot.click(target, "Login button")
bot.type_text(target, "Email field", "a@b.com", press_enter=True)
bot.double_click(target, "the file name to rename")                # double-click
bot.long_press(target, "the message bubble", duration=2.5)         # mobile: context menu
bot.key_down(target, "w"); bot.key_up(target, "w")                 # desktop: hold/release a key (pair them)
text = bot.extract(target, "the displayed account balance")        # read one thing
bot.wait_for(target, "the dashboard finished loading")             # gate, raises on timeout
```

`extract()` reads values off the screen; `verify()` returns a bool the script
can branch on. See Step 3 for when to use which after `bot.ai`.

See `references/REFERENCE.md` for the full API: constructor options, `bind()`,
navigation/scroll/keys, the per-platform action matrix, and errors.

## Step 3 — Check the result by who consumes it

Every run writes a self-contained HTML report with per-step screenshots to
`./qira_runs/<date>/<run>/report.html` (unless `report=False`). `bot.ai` leaves
three signals after it returns — pick by who acts on them:

- **A human/agent will read the result** → open the report and look at the step
  screenshots. Do NOT trust `result.success`: it's the same model that just
  acted, reporting on itself, and can claim victory after clicking the wrong
  button.
- **The script must branch on the outcome** (CI gate, `if logged_in skip
  login`, conditional flow) → `bot.verify(target, "...")`. Independent vision
  call, returns `bool`, costs one AI call. The bool must drive something —
  otherwise it's a billed call whose result goes nowhere, and the screenshot
  already tells the human reviewer the same thing for free.
- **The script needs to read a value** (price, username, status) →
  `bot.extract(target, "...")`. Beware ambiguous locates:
  `extract("the logged-in username")` can grab a rotating search-box hint
  instead — scope the phrase and cross-check against the screenshot.

When a run fails (`result.success=False`, or the screenshot looks wrong), the
**stdout `on_step` trace is the fastest entry point** — find the step where the
model started looping or chose a wrong action, then jump to that step's
screenshot in the report.

**Embed a screen video in the report.** The report auto-discovers a file named
`recording.mp4` in `bot.report_dir` and embeds it as a `<video>` at the top
(next to the step screenshots) — just put one there before `bot.close()`:

- **Desktop / browser** → let the SDK record the host screen for you:
  `Qirabot(record=True)` (or env `QIRA_RECORD=1`) runs ffmpeg into
  `recording.mp4`, no extra code.
- **Android / iOS (or any native framework)** → host capture can't see the
  device, so record the **device** with its own recorder and write it to
  `bot.report_dir/recording.mp4`. Start before `bot.ai` and **stop before
  `bot.close()`** (close scans for the file):
  - Airtest (Android): `device().start_recording(output=os.path.join(bot.report_dir, "recording.mp4"), max_time=1800)`, then `device().stop_recording(output=...)` in a `finally`.
  - Appium (iOS/Android): `driver.start_recording_screen()`, then write
    `base64.b64decode(driver.stop_recording_screen())` to that same path.

See `references/REFERENCE.md` (the `record` row) for details.

## Notes

- One script run = one Qirabot session = one task. State (the live
  page/driver) does not survive across separate `python` invocations, so put a
  whole task in one script. **To reuse a login across runs**, open with a
  persistent profile: `bot.open(url, user_data_dir=os.path.expanduser("~/.qira-profiles/<site>"))`
  (log in once, later runs start authenticated — see `references/REFERENCE.md`).
  NOTE: pass an **absolute** path — qirabot/Playwright do NOT expand `~`, so a
  literal `"~/..."` creates a `./~/` dir in the CWD. Use `os.path.expanduser`.
- **Confirm before irreversible or outward-facing actions** done under the
  user's identity (posting a comment, purchasing, deleting): gather/read first,
  report exactly what you're about to do, get the user's go-ahead, then act.
  Keep the read step and the action step separate.
- Costs real credits per AI call. Watch for `InsufficientBalanceError`. Pick the
  cheapest model that fits via `Qirabot(model_alias=...)` — `fast`/`balanced` for
  simple flows, stepping up only when needed (tiers in REFERENCE). Long
  human-in-the-loop waits (QR/OTP) poll with billed AI calls — raise the
  `wait_for` `interval` or poll the live driver instead (see REFERENCE).
- `bot.close()` (or the `with` form) finalizes the task and writes the report —
  always close, even on error.
