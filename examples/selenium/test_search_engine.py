"""Bolt-on AI to Selenium: test Wikipedia search.

Site: https://www.wikipedia.org

Run:
    pytest examples/selenium/test_search_engine.py
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from qirabot import Qirabot

bot = Qirabot(task_name="test-wikipedia-selenium", screenshot_dir="./screenshots")
driver = webdriver.Chrome()


def test_search_and_extract():
    driver.get("https://www.wikipedia.org")

    # Your existing Selenium code
    search = driver.find_element(By.ID, "searchInput")
    search.send_keys("Python programming language")
    search.send_keys(Keys.RETURN)

    # Bolt-on: AI extracts the summary
    summary = bot.extract(driver, "Get the first paragraph of the article")
    assert "Python" in summary


def test_verify_page_layout():
    driver.get("https://en.wikipedia.org/wiki/Python_(programming_language)")

    # Bolt-on: AI checks page structure visually
    assert bot.verify(driver, "Page has a table of contents")
    assert bot.verify(driver, "Page has an infobox with language details")


def test_navigate_sections():
    driver.get("https://en.wikipedia.org/wiki/Python_(programming_language)")

    # Bolt-on: AI clicks section link — no fragile selectors needed
    result = bot.ai(
        driver,
        "Click 'History' in the table of contents, extract the first sentence",
        max_steps=5,
    )
    assert result.success
    assert result.output
