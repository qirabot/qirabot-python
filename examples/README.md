# Qirabot examples

Two styles, two jobs:

## 1. Bolt onto your existing tests (pytest)

Add AI where selectors are fragile — visual assertions, fuzzy element
descriptions, unstructured extraction — while keeping the rest of your suite.
Organized by the framework you already use:

- [playwright/](playwright/) — `page` fixture from pytest-playwright
- [selenium/](selenium/) — your own `webdriver.Chrome()`
- [appium/](appium/) — Android / iOS via `webdriver.Remote`
- [desktop/](desktop/) — native apps via pyautogui

Run with `pytest examples/<framework>/`.

## 2. Standalone automation (plain scripts)

Build scraping / RPA / agent scripts. `bot.open()` launches its own browser —
no pytest, no fixtures, no webdriver setup. Run with `python`.

- [automation/](automation/) — `bot.open()`, `bot.ai()`, scraping, CDP connect

## Setup

```bash
export QIRA_API_KEY="qk_..."
```

Each subdirectory's README lists the extras to install for that style.
