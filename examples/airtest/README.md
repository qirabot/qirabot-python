# Airtest + Qirabot

Use Qirabot as a bolt-on AI layer on top of [Airtest](https://github.com/AirtestProject/Airtest).

Airtest is image/coordinate-based cross-platform UI automation (Android / iOS /
Windows) with a very light device connection — `connect_device("Android:///")`,
no Appium server. Its weak spot is brittle `Template` screenshots that break when
the UI shifts (resolution, theme, text, language). Qirabot replaces those with
natural-language targets and adds multi-step `ai()` / `extract` / `verify`.

## Install

```bash
pip install "qirabot[airtest]" pytest
```

> ⚠️ Airtest pins `numpy<2.0` and `opencv-contrib-python` 4.4–4.6. Installing into
> an environment that already has `numpy>=2` may downgrade or conflict — prefer a
> dedicated virtualenv.

## Connect a device

```bash
adb devices                 # Android: emulator or USB device must show up
export AIRTEST_DEVICE="Android:///"   # or e.g. "iOS:///..." / "Windows:///"
```

## Run

```bash
export QIRA_API_KEY="qk_..."
pytest examples/airtest/test_android_app.py
```

## How it works — `bind(G)` (recommended)

Airtest's idiom is a global current device (`G.DEVICE`) plus module-level
functions, so you usually don't hold a device handle. `bind(G)` matches that:
bind once, then drop the target from every call. It reads `G.DEVICE` lazily, so
it also follows `set_current()` multi-device switches.

```python
from airtest.core.api import *      # your usual Airtest imports
from qirabot import Qirabot

auto_setup(__file__)                # your usual Airtest setup, unchanged
bot = Qirabot(task_name="demo").bind(G)

bot.click("登录按钮")               # AI vision-located, no Template needed
bot.type_text("Search box", "qirabot", press_enter=True)
assert bot.verify("Results are shown")
bot.ai("Open Settings and turn on dark mode")

touch(Template("native.png"))       # native Airtest still works side by side
```

## Other ways to pass the target

All three of these resolve to the same adapter:

```python
import airtest.core.api as air

bot.click(G, "登录按钮")            # explicit G (no bind)
bot.click(air, "登录按钮")          # the airtest.core.api module
dev = connect_device("Android:///")
bot.click(dev, "登录按钮")          # an explicit device handle
```

## When Qirabot + Airtest fits (and when it doesn't)

Good fit:
- Your `Template` images keep breaking on UI changes → describe elements in words.
- You need reasoning Airtest can't do: multi-step `ai()`, `extract`, `verify`.
- Platforms Appium/pyautogui don't cover well: Windows desktop, games.

Weaker fit — keep native Airtest/Poco instead:
- Stable, high-volume regression suites where Templates already work (Qirabot adds
  per-action server latency + credit cost + some nondeterminism).
- Needing element-tree precision / attribute assertions (use Poco).
- Offline / air-gapped device farms (Qirabot calls the server).

## Capability notes

- `navigate` is not supported (Airtest has no URL concept). `go_back` works on
  Android only (`keyevent("BACK")`); iOS/Windows raise `NotImplementedError`.
- `clear_text` is best-effort on Android (caret-to-end + repeated delete); there
  is no element model to clear precisely.
- `keyevent` names are platform-specific; the key mapping is Android-first.

## Examples

Bolt-on to assertions (run with `pytest`):

- [test_android_app.py](test_android_app.py) — Android Settings: click, type, search, multi-step `ai()`
- [test_windows_app.py](test_windows_app.py) — Windows desktop (Calculator): a surface Appium doesn't cover

Standalone scripts (run with `python`):

- [standalone_rpa.py](standalone_rpa.py) — Android: hand a whole task to `bot.ai()`, no pytest
- [record_android_app.py](record_android_app.py) — Android: full run with `on_step` logging and a screen recording embedded in the report
- [standalone_windows_rpa.py](standalone_windows_rpa.py) — Windows desktop: same, driving Calculator
- [bolt_on_template.py](bolt_on_template.py) — mix native Airtest `Template` with qirabot AI (incremental migration)
