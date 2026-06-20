"""Qirabot browser automation template — Qirabot launches its own Chromium.

Fill in the TODOs, then run:
    python -m venv .qira-venv && source .qira-venv/bin/activate
    pip install "qirabot[browser]" && playwright install chromium
    export QIRA_API_KEY="qk_..."
    python browser.py

A self-contained HTML report (with screenshots) is written to
./qira_runs/<date>/<run>/report.html on close — open it to verify the run.
"""

from qirabot import Qirabot

# TODO: starting URL + the task to perform
START_URL = "https://www.saucedemo.com"
TASK = "Log in as standard_user / secret_sauce, then add the cheapest item to the cart"

with Qirabot(task_name="browser-template", model_alias="balanced") as bot:
    page = bot.open(START_URL, headless=False)

    # Default: hand the whole task to qirabot's agent loop (self-heals).
    result = bot.ai(page, TASK, max_steps=15)
    print("success:", result.success)
    print("output:", result.output)

    # Confirm the outcome (cheap checks).
    ok = bot.verify(page, "an item is in the shopping cart")
    print("item in cart:", ok)

    # --- Optimization: for a stable flow you'll run repeatedly, hand-script the
    # --- steps instead (cheaper per action, deterministic, but brittle):
    # bot.type_text(page, "Username field", "standard_user")
    # bot.type_text(page, "Password field", "secret_sauce", press_enter=True)
    # bot.click(page, "Add to cart on the cheapest item")
