"""Bolt-on AI to Playwright: test an e-commerce site.

Install:
    python -m pip install qirabot pytest-playwright
    playwright install chromium

Run:
    pytest examples/playwright/test_ecommerce.py
    pytest examples/playwright/test_ecommerce.py --headed
"""

from qirabot import Qirabot

bot = Qirabot(task_name="test-ecommerce")


def test_login(page):
    page.goto("https://www.saucedemo.com")

    # Your existing Playwright code
    page.fill("#user-name", "standard_user")
    page.fill("#password", "secret_sauce")
    page.click("#login-button")

    # Bolt-on: AI verifies the result
    assert bot.verify(page, "Product listing page is displayed")


def test_login_error(page):
    page.goto("https://www.saucedemo.com")
    page.fill("#user-name", "bad_user")
    page.fill("#password", "bad_pass")
    page.click("#login-button")

    # Bolt-on: check error message without knowing exact text
    assert bot.verify(page, "An error message is shown")


def test_add_to_cart(page):
    page.goto("https://www.saucedemo.com")
    page.fill("#user-name", "standard_user")
    page.fill("#password", "secret_sauce")
    page.click("#login-button")

    # Your existing code
    page.click('[data-test="add-to-cart-sauce-labs-backpack"]')

    # Bolt-on: AI checks the cart badge
    assert bot.verify(page, "Shopping cart badge shows 1")

    # Bolt-on: AI extracts product info
    name = bot.extract(page, "What is the name of the first product?")
    assert "Backpack" in name


def test_checkout(page):
    page.goto("https://www.saucedemo.com")
    page.fill("#user-name", "standard_user")
    page.fill("#password", "secret_sauce")
    page.click("#login-button")
    page.click('[data-test="add-to-cart-sauce-labs-backpack"]')
    page.click(".shopping_cart_link")

    # Bolt-on: AI handles the checkout form
    result = bot.ai(
        page,
        "Click checkout, fill name 'John Doe', zip '10001', finish the order",
        max_steps=10,
    )
    assert result.success
