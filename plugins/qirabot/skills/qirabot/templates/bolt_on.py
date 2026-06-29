"""Qirabot bolt-on template — add AI to a driver you build yourself.

Use this for native desktop, or any case where you already construct a
Selenium / Appium driver: build the framework object as usual, `bind()` it once,
then drive it by natural language. (For "Qirabot launches Chromium" use
templates/browser.py; for Android over Airtest use templates/android.py; for
iOS use templates/ios_airtest.py or templates/ios_appium.py — both cover
real-device WDA reuse.)

The concrete example below is Selenium. Swap the marked block for one of the
Appium, pyautogui (whole-screen desktop, any OS), or Airtest (window-scoped
Windows desktop) variants at the bottom.

Run (Selenium):
    python -m venv .venv && source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
    pip install qirabot selenium        # Appium: qirabot[appium] · desktop: qirabot[desktop]
    echo 'QIRA_API_KEY=qk_...' > .env    # load_dotenv() reads this (also QIRA_BASE_URL)
    python bolt_on.py

The HTML report is written to ./qira_runs/<date>/<run>/report.html on close.
"""

from selenium import webdriver

from qirabot import Qirabot, StepResult, load_dotenv

# Read QIRA_API_KEY / QIRA_BASE_URL from ./.env (a real exported env var wins).
load_dotenv()

# TODO: the task to perform (and the start URL / app for your target)
START_URL = "https://www.wikipedia.org"
TASK = "Search for 'Alan Turing' and open his article"


def on_step(step: StepResult) -> None:
    # Print each step so the whole run is traceable from stdout — not just the
    # HTML report. Shows the model's per-step decision live, so a failed or
    # looping run is debuggable straight from the console.
    label = "done" if step.finished else step.action_type
    print(f"  step {step.step}: {label} {step.params} — {step.decision}")


# --- You build the driver (plain Selenium here; Selenium 4 fetches its own driver) ---
driver = webdriver.Chrome()
driver.get(START_URL)

# bind() once: the driver is stable for the whole session, so every call drops the
# repeated first arg — bot.click("...") instead of bot.click(driver, "...").
with Qirabot(task_name="bolt-on-template", model_alias="balanced").bind(driver) as bot:
    # Default: hand the whole task to qirabot's agent loop (self-heals).
    result = bot.ai(TASK, max_steps=15, on_step=on_step)
    print("success:", result.success)
    print("output:", result.output)

    # Confirm the outcome (cheap check).
    ok = bot.verify("the Alan Turing article is open")
    print("article open:", ok)

driver.quit()


# --- Android via Appium UiAutomator2 (needs a running Appium server) ---------
# For iOS use templates/ios_airtest.py or templates/ios_appium.py instead —
# they cover real-device capabilities (udid / WDA reuse / signing) and, in the
# Appium case, device screen recording.
# from appium import webdriver
# from appium.options.android import UiAutomator2Options
#
# options = UiAutomator2Options()
# options.platform_name = "Android"
# options.app_package = "com.android.settings"
# options.app_activity = ".Settings"
# driver = webdriver.Remote("http://localhost:4723", options=options)
# with Qirabot(task_name="android-bolt-on").bind(driver) as bot:
#     result = bot.ai("Open Display settings and turn on Dark theme")
#     print(result.success, result.output)
# driver.quit()


# NOTE (Windows): if the target app/game runs as Administrator (common for games
# with anti-cheat), run this script as Administrator too — else Windows UIPI
# silently drops clicks/keystrokes (cursor moves, nothing happens, no error).


# --- Native desktop via pyautogui (drives the WHOLE primary screen, any OS) --
# import pyautogui
#
# with Qirabot(task_name="desktop-bolt-on").bind(pyautogui) as bot:
#     bot.launch_app("Notes")            # open the app first — pyautogui can't navigate
#     result = bot.ai("Create a new note titled 'Groceries'")
#     print(result.success, result.output)


# --- Windows desktop via Airtest (pywinauto — scopes to ONE window) ----------
# Prefer this over pyautogui on Windows when you must target a single window
# (by HWND) instead of the whole screen. Needs qirabot[airtest].
# from airtest.core.api import connect_device, G
#
# connect_device("Windows:///")          # or "Windows:///<hwnd>" for one window
# with Qirabot(task_name="windows-bolt-on").bind(G) as bot:
#     result = bot.ai("Create a new note titled 'Groceries'")
#     print(result.success, result.output)
