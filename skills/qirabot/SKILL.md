---
name: qirabot
description: Drive any GUI with natural language — click, type, extract, and verify on web browsers, Android, iOS, desktop apps, and games — using the Qirabot Python SDK. Use this when the user wants to automate, test, or scrape a user interface by describing elements in plain language instead of CSS/XPath selectors; when driving a mobile app or a native desktop/game where DOM-based tools don't work; or for visual UI verification, screenshots, and RPA. Triggers include: automate a website or app, UI/end-to-end test, fill a form, scrape a page, tap or click a button, verify what's on screen, drive an Android/iOS app, automate a desktop application.
license: MIT
compatibility: Requires Python >=3.10 (browser/desktop also run on 3.13; use 3.10-3.12 only for the Android/airtest extra, whose numpy/opencv wheels stop at 3.12), a QIRA_API_KEY (get one at https://app.qirabot.com), and the target runtime — Playwright+Chromium for browser, adb+device for Android, the app installed for desktop. ffmpeg optional for screen recording.
metadata:
  author: qirabot
  version: "0.1.0"
---

# Qirabot automation

Give an agent eyes and hands for any GUI. Qirabot locates elements by
**natural-language description** (no selectors) and works the same way across
browser, Android, iOS, native desktop, and canvas/game UIs.

## When to use this vs. not

- **Use it** for: mobile apps, native desktop apps, games/canvas/Flutter (no
  usable DOM), visual assertions ("the success banner is green"), and any "do
  this on the screen" task described in plain language.
- **Consider a DOM tool instead** for *pure web* automation when the host
  already has a browser/DOM tool available — it can be cheaper and faster.
  Qirabot's edge is the non-web and visual cases.

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

# android/airtest needs its OWN venv on Python 3.10-3.12 — it pins numpy<2 and
# would downgrade/conflict a shared env:
python3.12 -m venv .qira-venv-airtest && source .qira-venv-airtest/bin/activate
pip install "qirabot[airtest]"

export QIRA_API_KEY="qk_..."        # from https://app.qirabot.com
```

## Step 1 — Pick a target and start from a template

| Target | Template | Extra |
|---|---|---|
| Web browser (Qirabot launches Chromium) | `templates/browser.py` | `qirabot[browser]` + `playwright install chromium` |
| Android (Airtest, no Appium server) | `templates/android.py` | `qirabot[airtest]` (Python 3.10-3.12) |

Copy the template, fill in the `TODO`s (start URL / app package, and the task),
then run it with **the interpreter preflight echoed** (its absolute path), not a
bare `python`. For iOS/desktop/Selenium/Appium variants see
`references/REFERENCE.md`.

## Step 2 — Hand the task to qirabot (default), drop to primitives only to optimize

**Default: give the whole task to `bot.ai`.**

```python
result = bot.ai(target, "Add the cheapest item to the cart and check out",
                max_steps=15)
print(result.success, result.output)
```

`bot.ai` offloads the perceive → decide → act loop to qirabot, which manages its
own step history and self-heals when a step misfires. The agent does NOT plan or
micromanage each click — it states the goal once. Then confirm the outcome:

```python
ok = bot.verify(target, "the order confirmation page is shown")   # cheap, bool
```

**Drop to the per-step primitives only as a deliberate optimization** — when you
want strict, reproducible determinism, or you're codifying a stable flow to run
repeatedly (e.g. a CI regression check). They cost less per action and are
reproducible, but are brittle to UI changes:

```python
bot.click(target, "Login button")
bot.type_text(target, "Email field", "a@b.com", press_enter=True)
text = bot.extract(target, "the displayed account balance")        # read one thing
bot.wait_for(target, "the dashboard finished loading")             # gate, raises on timeout
```

`extract()` / `verify()` are cheap and useful regardless — use them to read
values and check results even when the actions came from `bot.ai`.

See `references/REFERENCE.md` for the full API: constructor options, `bind()`,
navigation/scroll/keys, the per-platform action matrix, and errors.

## Step 3 — Verify the result from the report, not assumptions

Every run writes a self-contained HTML report with per-step screenshots to
`./qira_runs/<date>/<run>/report.html` (unless `report=False`). After running,
**open/inspect that report (or call `bot.screenshot(target)`) to confirm what
actually happened** — the model can act on (or read back) a misread screen, so
don't report success without looking. Identity/state reads are especially
slippery: `extract(target, "the logged-in username")` may return a rotating
search-box hint rather than the account — confirm such values against the
screenshot before reporting them.

## Notes

- One script run = one Qirabot session = one task. State (the live
  page/driver) does not survive across separate `python` invocations, so put a
  whole task in one script. **To reuse a login across runs**, open with a
  persistent profile: `bot.open(url, user_data_dir="~/.qira-profiles/<site>")`
  (log in once, later runs start authenticated — see `references/REFERENCE.md`).
- **Confirm before irreversible or outward-facing actions** done under the
  user's identity (posting a comment, purchasing, deleting): gather/read first,
  report exactly what you're about to do, get the user's go-ahead, then act.
  Keep the read step and the action step separate.
- Costs real credits per AI call. Watch for `InsufficientBalanceError`. Long
  human-in-the-loop waits (QR/OTP) poll with billed AI calls — raise the
  `wait_for` `interval` or poll the live driver instead (see REFERENCE).
- `bot.close()` (or the `with` form) finalizes the task and writes the report —
  always close, even on error.
