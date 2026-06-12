# -*- encoding=utf8 -*-
"""Standalone Android RPA with a screen recording embedded in the run report.

This is the full-featured cousin of ``standalone_android_rpa.py``: it drives a
specific app, streams every step, and records the screen with Airtest's native
recorder. The SDK does not record for you — point Airtest's recorder at
``bot.report_dir`` and the HTML report embeds the resulting ``recording.mp4``.

Install:
    pip install "qirabot[airtest]"

Run (connect an emulator/device via adb first):
    export QIRA_API_KEY="qk_..."
    python examples/airtest/record_android_app.py

The ``cli_setup()`` guard lets the same file run both via ``airtest run ...``
(IDE / CI, which calls ``cli_setup()`` for you) and as a plain ``python`` script.
"""

import os

from airtest.cli.parser import cli_setup
from airtest.core.api import G, auto_setup, device, sleep, start_app, stop_app

from qirabot import Qirabot, StepResult

# When launched outside `airtest run ...`, set up the device ourselves. The
# connection string selects the device and touch backend (MAXTOUCH here).
if not cli_setup():
    auto_setup(
        __file__,
        logdir=True,
        devices=["android://127.0.0.1:5037/127.0.0.1:5555?touch_method=MAXTOUCH&"],
    )

# Credentials — prefer setting these in the environment, not in source.
# QIRA_BASE_URL is optional: it defaults to https://app.qirabot.com. Set it only
# for a self-hosted or regional deployment (the URL below is one such example).
os.environ.setdefault("QIRA_BASE_URL", "https://app.gcp.qirabot.com")
os.environ.setdefault("QIRA_API_KEY", "qk_...your_key...")

# The app to drive and the task to carry out, in plain language.
APP = "com.pokercity.lobby"
TASK = "Check that the UI controls at the top of the poker lobby work correctly"


def on_step(step: StepResult) -> None:
    label = "done" if step.finished else step.action_type
    print(f"  step {step.step}: {label} {step.params}")


start_app(APP)

# balanced_pro = stronger model; screenshot_annotate draws a crosshair at each tap.
bot = Qirabot(model_alias="balanced_pro", screenshot_annotate=True).bind(G)

# Record into the per-run dir so the report embeds it
# (qira_runs/<date>/<run>/recording.mp4).
video = os.path.join(bot.report_dir, "recording.mp4")
device().start_recording(output=video, max_time=1800)
try:
    result = bot.ai(TASK, max_steps=25, on_step=on_step, language="en")
    print(f" Result: {result.output}")
    sleep(5.0)
finally:
    saved = device().stop_recording(output=video)
    print(f" Recording saved: {saved}")
    bot.close()  # writes report.html with the video embedded

stop_app(APP)
