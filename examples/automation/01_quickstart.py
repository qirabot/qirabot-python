"""Standalone automation: let Qirabot launch its own browser.

Unlike the pytest examples (which bolt onto your existing test suite), this is a
plain script you run directly — no pytest, no fixtures, no webdriver setup.
bot.open() launches a Playwright-driven Chromium for you.

Install:
    pip install "qirabot[browser]"
    playwright install chromium

Run:
    export QIRA_API_KEY="qk_..."
    python examples/automation/01_quickstart.py
"""

from qirabot import Qirabot

bot = Qirabot(task_name="quickstart", screenshot_dir="./screenshots", model_alias="fast",screenshot_annotate=True)

# Qirabot launches the browser and returns a Playwright page.
page = bot.open("https://www.wikipedia.org", headless=False, user_data_dir="~/.automation")

# Drive it with natural-language descriptions instead of selectors.
bot.type_text(page, "Search input", "Python programming language", press_enter=True)

summary = bot.extract(page, "Get the first paragraph of the article")
print("Extracted summary:")
print(summary)

ok = bot.verify(page, "An article about the Python language is shown")
print(f"\nOn the right page? {ok}")

bot.close()
