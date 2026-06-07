"""Standalone Windows desktop RPA with Airtest: hand a whole task to the AI.

The plain-`python` counterpart to test_windows_app.py. Airtest drives native
Windows apps (a surface Appium doesn't cover); `bot.ai()` runs the full decision
loop. Opens the app, lets the AI work, then closes it.

Install:
    pip install "qirabot[airtest]"

Run (Windows only):
    set QIRA_API_KEY=qk_...
    python examples/airtest/standalone_windows_rpa.py
"""

import sys

from airtest.core.api import G, connect_device, keyevent

from qirabot import Qirabot, StepResult

if sys.platform != "win32":
    sys.exit("This example requires Windows (Airtest Windows backend).")

TASK = "Compute 42 + 58 in Calculator and report the result"


def on_step(step: StepResult) -> None:
    label = "done" if step.finished else step.action_type
    print(f"  step {step.step}: {label} {step.params}")


# Connect to the whole desktop (or one window via
# connect_device("Windows:///?title_re='.*Calculator.*'")).
connect_device("Windows:///")

# The finally closes the app whether the run succeeds or not. Windows' stop_app()
# needs a PID, so close the focused window with Alt+F4 (pywinauto syntax).
try:
    with Qirabot(task_name="airtest-windows-rpa").bind(G) as bot:
        bot.launch_app("calc", wait=2)  # open the app
        result = bot.ai(TASK, max_steps=12, on_step=on_step)

    print(f"\nSuccess: {result.success}")
    print(f"Output: {result.output}")
    print(f"Steps taken: {len(result.steps)}")
finally:
    keyevent("%{F4}")  # close the app
