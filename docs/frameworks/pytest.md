---
title: AI Visual Assertions in pytest — Self-Healing UI Tests
description: Use Qirabot inside pytest suites - visual assertions with bot.verify(), on-screen data extraction, autonomous flow steps with bot.ai(), fixtures, and per-run HTML reports with screenshots.
---

# pytest + Qirabot

Qirabot slots into pytest as a library: one `Qirabot` instance per test (or
per session via a fixture), assertions on what the screen *shows*, and an
HTML report with per-step screenshots for every run — including failures.

## With pytest-playwright

```python
from qirabot import Qirabot

bot = Qirabot(task_name="test-checkout")

def test_checkout(page):          # your existing pytest-playwright fixture
    page.goto("https://shop.example.com")

    # Your existing Playwright selectors — keep them as-is
    page.fill("#username", "test_user")
    page.fill("#password", "secret")
    page.click("#login-btn")

    # AI verifies without knowing exact text or selector
    assert bot.verify(page, "Product listing page is displayed")

    page.click('[data-test="add-to-cart"]')
    assert bot.verify(page, "Cart badge shows 1 item")

    # Hand the dynamic tail of the flow to the AI
    result = bot.ai(page, "Complete checkout, name John Doe zip 10001", max_steps=8)
    assert result.success
```

## As a fixture

```python
import pytest
from qirabot import Qirabot

@pytest.fixture(scope="session")
def bot():
    b = Qirabot(report_dir="./artifacts")
    yield b
    b.close()          # writes the HTML report, marks the server task complete

def test_search(bot, page):
    page.goto("https://www.wikipedia.org")
    bot.type_text(page, "the search box", "SpaceX", press_enter=True)
    assert bot.verify(page, "the SpaceX article is shown")
```

`close()` is also covered by `atexit` if a test hard-crashes, and the server
times out orphaned tasks after 30 minutes.

## Assertion patterns

```python
# Boolean check — never raises, ideal for assert
assert bot.verify(page, "the error banner is NOT visible")

# Gate — raises QirabotTimeoutError on timeout, poll until true
bot.wait_for(page, "the spinner is gone", timeout=15.0)

# Value assertions via extraction
count = bot.extract(page, "the number on the cart badge as an integer")
assert count == 1
```

Prefer `wait_for` over sleeps: it returns as soon as the condition holds.

## CI notes

- Reports: point them at your artifacts dir (`Qirabot(report_dir=...)` or
  `QIRA_REPORT_DIR`), and upload `qira_runs/` on failure — the report shows
  the exact screenshot at each step.
- Turn reports off entirely with `Qirabot(report=False)` if you only want
  the assertions.
- API key comes from `QIRA_API_KEY` (env var beats the `qirabot login`
  config — CI-friendly). Exit codes on the CLI are script-friendly too:
  `0` pass, `1` fail, `130` interrupted.
- Headless: on display-less runners the managed browser automatically goes
  headless.

Related: [Playwright](/frameworks/playwright) ·
[Selenium](/frameworks/selenium) · [Reports & Recording](/advanced/reports)
