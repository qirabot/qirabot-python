"""Bolt-on AI to Playwright: test form validation.

Install:
    python -m pip install qirabot pytest-playwright
    playwright install chromium

Run:
    pytest examples/playwright/test_form_validation.py
"""

from qirabot import Qirabot

bot = Qirabot(task_name="test-form")

URL = "https://demoqa.com/automation-practice-form"


def test_empty_submit_shows_errors(page):
    page.goto(URL)

    # Your existing code
    page.evaluate("document.getElementById('submit').click()")

    # Bolt-on: AI checks if fields turned red
    assert bot.verify(page, "Required fields are highlighted in red")


def test_fill_and_submit(page):
    page.goto(URL)

    # Your existing code
    page.fill("#firstName", "Jane")
    page.fill("#lastName", "Doe")
    page.click('label[for="gender-radio-2"]')
    page.fill("#userNumber", "1234567890")
    page.evaluate("document.getElementById('submit').click()")

    # Bolt-on: AI checks the success modal
    assert bot.verify(page, "A success confirmation is displayed")


def test_date_picker(page):
    """Date pickers are hard to automate — let AI handle it."""
    page.goto(URL)

    result = bot.ai(
        page,
        "Click Date of Birth, select year 1990, month January, day 15",
        max_steps=8,
    )
    assert result.success
