"""Tests for the optional-dependency install hints (qirabot._optional.require)."""

from unittest.mock import MagicMock

import pytest

from qirabot import _optional
from qirabot.exceptions import MissingDependencyError


@pytest.fixture
def missing_everything(monkeypatch):
    """Make every import fail so the hints are testable regardless of what the
    dev environment actually has installed."""
    monkeypatch.setattr(
        _optional.importlib, "import_module", MagicMock(side_effect=ImportError)
    )


def test_extra_package_hints_the_qirabot_extra(missing_everything):
    with pytest.raises(MissingDependencyError) as ei:
        _optional.require("playwright.sync_api")
    assert 'python -m pip install "qirabot[browser]"' in str(ei.value)


def test_selenium_hints_plain_pip_install(missing_everything):
    """Selenium is deliberately not an extra (bring-your-own driver); the hint
    must not point at a nonexistent qirabot[selenium]."""
    with pytest.raises(MissingDependencyError) as ei:
        _optional.require("selenium.webdriver")
    msg = str(ei.value)
    assert "python -m pip install selenium" in msg
    assert "qirabot[" not in msg


def test_explicit_extra_still_wins(missing_everything):
    with pytest.raises(MissingDependencyError) as ei:
        _optional.require("airtest.core.api", "airtest")
    assert 'python -m pip install "qirabot[airtest]"' in str(ei.value)
