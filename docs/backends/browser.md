---
title: AI Browser Automation in Python (Playwright)
description: Automate Chrome with AI vision instead of CSS selectors — Qirabot launches Chromium for you or bolts onto your existing Playwright or Selenium session. Headless, persistent profiles, CDP attach.
---

# Browser Automation

Qirabot drives the browser through **pixels, not the DOM**. The AI reads the
rendered page like a person does, so it works where selector-based automation
breaks: canvas apps, cross-origin iframes, shadow DOM, aggressive A/B-tested
layouts, and pages that change faster than your test suite.

You can let Qirabot manage the browser, or bolt it onto the Playwright /
Selenium session you already have.

## Managed browser

`bot.open()` launches Chromium (Playwright under the hood) — you never write
framework code:

```python
from qirabot import Qirabot

bot = Qirabot()
page = bot.open("https://news.ycombinator.com")

result = bot.ai(page, "Open the top story and summarize the discussion")
print(result.output)

bot.close()
```

Requires the `browser` extra: `pip install "qirabot[browser]"` then
`qirabot install-browser`.

From the CLI, the same run is one command:

```bash
qirabot browser "Open the top story and summarize the discussion" --url news.ycombinator.com
qirabot browser "..." --headless --viewport 1920x1080
qirabot browser "..." --user-data-dir ~/.qira-profile --channel chrome   # logins survive runs
qirabot browser "..." --cdp-url http://localhost:9222                    # attach to running Chrome
```

`--cdp-url` also works with remote pools like browserless.

## Bolt onto Playwright

Pass your existing `page` — mix your selectors with AI steps freely:

```python
from playwright.sync_api import sync_playwright
from qirabot import Qirabot

bot = Qirabot()

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("https://github.com/trending")

    repos = bot.extract(page, "Get the top 5 trending repo names")
    print(repos)

    browser.close()
bot.close()
```

For Playwright, keep the explicit form `page = bot.click(page, ...)` — a click
can open a new tab, and the returned page is the one your native
`page.fill(...)` calls should use. `bot.go_back()` is smart about this: if a
click opened a link in a new tab (which starts with no history), it closes the
tab and returns to the previous one, so the common "open item, go back to the
list" loop just works:

```python
for i in range(4):
    page = bot.click(page, locate=f"open video {i + 1}")  # opens a new tab
    bot.screenshot(page)
    page = bot.go_back(page)                               # closes it, back to the list
```

## Bolt onto Selenium

```python
from selenium import webdriver
from qirabot import Qirabot

driver = webdriver.Chrome()
driver.get("https://www.wikipedia.org")
bot = Qirabot().bind(driver)   # bind once; the driver is stable for the session

summary = bot.extract("Get the first paragraph of the article")
print(summary)

driver.quit()
bot.close()
```

Selenium is not an extra — bring your own driver
(`pip install qirabot selenium`).

## In a pytest suite

Keep your existing selectors and driver code; swap in AI assertions and AI
steps only where things break:

```python
from qirabot import Qirabot

bot = Qirabot(task_name="test-checkout")

def test_checkout(page):          # your existing pytest-playwright fixture
    page.goto("https://shop.example.com")

    page.fill("#username", "test_user")     # your selectors, as-is
    page.fill("#password", "secret")
    page.click("#login-btn")

    # AI verifies without knowing exact text or selector
    assert bot.verify(page, "Product listing page is displayed")

    result = bot.ai(page, "Complete checkout, name John Doe zip 10001", max_steps=8)
    assert result.success
```

## Notes

- Headless detection: on a display-less box (no `DISPLAY`), `bot.open()` and
  the CLI automatically run headless, with a warning.
- `close_tab` is Playwright-only; `navigate`, `go_back`, `press_key`
  (including `ctrl+t`/`ctrl+w` tab switching — reassign the returned page),
  and `scroll` all work. See the full per-platform action matrix in the
  [API Reference](/reference/api#platform-support-matrix).
