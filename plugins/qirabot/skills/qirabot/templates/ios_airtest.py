"""Qirabot iOS automation template (Airtest — drives WDA directly, no Appium server).

Uses airtest's facebook-wda backend, which talks straight to WebDriverAgent
(WDA) over HTTP. Fewer moving parts than ios_appium.py (no `appium` server
process, no XCUITest driver), but launches use a WDA call directly — see below.

Zero go-ios dependency: every action in this template (screenshot, tap, type,
app launch) goes through WDA. The go-ios binary that ships inside the airtest
wheel is never invoked, so iOS 17+ devices do NOT need `sudo ios tunnel start`
or a RemoteXPC tunnel daemon. (The binary is still on disk — airtest packages
it — it's just unused here.)

Prereqs (real device):
    1. WDA built/signed once via Xcode and currently running on the device.
       (Same as ios_appium.py — qirabot can't drive iOS without WDA.)
    2. WDA reachable at http://127.0.0.1:8100. The standard USB path is iproxy
       in a separate terminal:
           iproxy 8100 8100        # brew install libimobiledevice
       Verify it returns "ready":
           curl http://127.0.0.1:8100/status

Install:
    python -m venv .venv && source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
    pip install "qirabot[airtest]"       # 3.10-3.12 fully supported (3.13 needs a C toolchain)
    echo 'QIRA_API_KEY=qk_...' > .env    # load_dotenv() reads this (also QIRA_BASE_URL)

When to pick this over ios_appium.py:
    - You already have WDA running on :8100 and don't want an Appium server.
    - Faster cold-start (no XCUITest driver attach).
    Pick ios_appium.py instead for simulator support, auto WDA build/sign, or
    first-party Appium ecosystem features.

The HTML report is written to ./qira_runs/<date>/<run>/report.html on close.
"""

from airtest.core.api import G, connect_device

from qirabot import Qirabot, StepResult, load_dotenv

# Read QIRA_API_KEY / QIRA_BASE_URL from ./.env (a real exported env var wins).
load_dotenv()

# TODO: the app under test and what you want done
WDA_URL = "http://127.0.0.1:8100"
BUNDLE_ID = "com.apple.Preferences"     # the app to drive; Settings as a safe default
TASK = "Open General and show the software version"

connect_device(f"iOS:///{WDA_URL}")


def on_step(step: StepResult) -> None:
    # Print each step so the whole run is traceable from stdout — not just the
    # HTML report. Shows the model's per-step decision live, so a failed or
    # looping run is debuggable straight from the console.
    label = "done" if step.finished else step.action_type
    print(f"  step {step.step}: {label} {step.params} — {step.decision}")


# Launch the app via WDA directly. Don't use airtest's start_app(): on a locally-
# attached device it routes through the bundled go-ios CLI, which on iOS 17+
# needs a RemoteXPC tunnel daemon the bundled binary doesn't start — the call
# fails with an opaque "CMD excute failed" error. The WDA app_launch endpoint
# works on every iOS version with no extra setup.
G.DEVICE.driver.app_launch(BUNDLE_ID)


with Qirabot(task_name="ios-airtest-template", model_alias="balanced_pro").bind(G) as bot:
    # Default: hand the whole task to qirabot's agent loop (self-heals).
    result = bot.ai(TASK, max_steps=20, on_step=on_step)
    print("success:", result.success)
    print("output:", result.output)

    # Confirm the outcome (cheap check).
    # ok = bot.verify("the software version is shown")


# --- Note on device recording -------------------------------------------------
# airtest's device().start_recording works on Android but is not implemented for
# iOS. To embed a device video in the report, switch to ios_appium.py (which
# uses driver.start_recording_screen) or pre-record with QuickTime / xcrun.
