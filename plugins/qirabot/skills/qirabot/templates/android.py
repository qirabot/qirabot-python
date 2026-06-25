"""Qirabot Android automation template (Airtest — no Appium server needed).

Fill in APP and TASK, then run:
    # use Python 3.10-3.12 for the airtest extra
    python -m venv .qira-venv && source .qira-venv/bin/activate
    pip install "qirabot[airtest]"
    export QIRA_API_KEY="qk_..."
    adb devices            # confirm a device/emulator is connected
    python android.py

Drives the *device* by natural language — no Template images, no selectors.
The HTML report is written to ./qira_runs/<date>/<run>/report.html on close.
"""

from airtest.core.api import G, auto_setup, start_app, stop_app

from qirabot import Qirabot, StepResult

# TODO: the app under test and what you want done
APP = "com.android.settings"
TASK = "Open Display settings and turn on Dark theme"

auto_setup(__file__)  # connect to the current adb device


def on_step(step: StepResult) -> None:
    # Print each step so the whole run is traceable from stdout — not just the
    # HTML report. Shows the model's per-step decision live, so a failed or
    # looping run is debuggable straight from the console.
    label = "done" if step.finished else step.action_type
    print(f"  step {step.step}: {label} {step.params} — {step.decision}")


start_app(APP)
with Qirabot(task_name="android-template", model_alias="balanced_pro").bind(G) as bot:
    # Default: hand the whole task to qirabot's agent loop (self-heals).
    result = bot.ai(TASK, max_steps=20, on_step=on_step)
    print("success:", result.success)
    print("output:", result.output)

    # Confirm the outcome (cheap check).
    # ok = bot.verify("dark theme is enabled")

    # --- Optimization: for a stable flow you'll run repeatedly, hand-script the
    # --- steps instead (cheaper per action, deterministic, but brittle):
    # bot.click("the Display menu item")
    # bot.click("the Dark theme toggle")
stop_app(APP)
