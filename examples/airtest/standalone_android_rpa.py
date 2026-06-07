"""Standalone mobile RPA with Airtest: hand a whole task to the AI.

Unlike the pytest examples in this folder (which bolt AI onto assertions), this
is a plain script you run with `python`. Airtest connects to the device itself
(no Appium server); from there `bot.ai()` runs the full decision loop — look at
the screen, pick the next action, repeat until done or max_steps is hit.

Install:
    pip install "qirabot[airtest]"

Run (connect an emulator/device via adb first):
    export QIRA_API_KEY="qk_..."
    python examples/airtest/standalone_rpa.py

Environment variables:
    export AIRTEST_DEVICE="Android:///"          # default; any connect_device URI
"""

import os

from airtest.core.api import G, connect_device, start_app, stop_app

from qirabot import Qirabot, StepResult

# The task to carry out, in plain language. Change this to whatever you need.
APP = "com.android.settings"
TASK = "Go to About Phone and report the Android version"

connect_device(os.environ.get("AIRTEST_DEVICE", "Android:///"))
start_app(APP)  # open the app


def on_step(step: StepResult) -> None:
    label = "done" if step.finished else step.action_type
    print(f"  step {step.step}: {label} {step.params}")


# The with-block reports the task as failed (or cancelled on Ctrl+C) if anything
# raises, and completed otherwise — so the run shows the right status in Qirabot.
# bind(G) means the ai() call below doesn't repeat the device target. The finally
# closes the app whether the run succeeds or not.
try:
    with Qirabot(task_name="airtest-rpa").bind(G) as bot:
        result = bot.ai(TASK, max_steps=12, on_step=on_step)

    print(f"\nSuccess: {result.success}")
    print(f"Output: {result.output}")
    print(f"Steps taken: {len(result.steps)}")
finally:
    stop_app(APP)  # close the app
