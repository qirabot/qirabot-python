"""Sample job for the desktop runner.

Write and test this on your own machine, then drop it into the remote runner's
inbox (e.g. scp sample_job.py user@vm:/path/to/runner-data/inbox/). It is a
plain standalone Qirabot script — the runner just does `python sample_job.py`
inside the remote machine's logged-in desktop session.

Anything you print goes to the job's .log next to the runner; printing the
task_id lets you open the run in the web console without watching the screen.
"""

import pyautogui
from qirabot import Qirabot

bot = Qirabot(task_name="sample-notepad-job")
print("task_id:", bot.task_id)  # -> results/<name>.log, view this run in the web console

# pyautogui can't launch apps, so open the target first. On Windows use "notepad";
# on macOS "TextEdit"; on Linux the editor's executable name.
bot.launch_app("notes", wait=2)

result = bot.ai(
    pyautogui,
    "Type the sentence 'Hello from the remote runner.' into the editor.",
    max_steps=10,
)

print("success:", result.success)
print("output:", result.output)

bot.close()
