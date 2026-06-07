"""Sample job for the desktop runner.

Write and test this on your own machine, then drop it into the remote runner's
inbox (e.g. scp sample_job.py user@vm:/path/to/runner-data/inbox/). It is a
plain standalone Qirabot script — the runner just does `python sample_job.py`
inside the remote machine's logged-in desktop session.

Anything you print goes to the job's .log next to the runner; printing the
task_id lets you open the run in the web console without watching the screen.
"""

import logging

import pyautogui
from qirabot import Qirabot

# The SDK logs each step ("step 3/10 <decision> -> click ...") at INFO level, but
# Python emits nothing until logging is configured. Turn it on so the runner can
# stream live progress back to you; without this you'd only see the prints below.
logging.basicConfig(level=logging.INFO, format="%(message)s")
# basicConfig turns on INFO for every library; quiet httpx so only the SDK's
# "step N/10 ..." lines show, not a "HTTP Request: ..." line per call.
logging.getLogger("httpx").setLevel(logging.WARNING)

bot = Qirabot(task_name="sample-notepad-job", model_alias="balanced_pro")
print("task_id:", bot.task_id, flush=True)  # open this run in the web console

# pyautogui can't launch apps, so open the target first. On Windows use "notepad";
# on macOS "TextEdit"; on Linux the editor's executable name.
bot.launch_app("google chrome", wait=2)

result = bot.ai(
    pyautogui,
    "What are the top trending projects on GitHub today, output in Markdown format",
    max_steps=10,
)

print("success:", result.success)
print("output:", result.output)

bot.close()
