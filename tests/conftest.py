"""Shared test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_user_config(tmp_path, monkeypatch):
    """Point the user-level config dir at a temp path for every test.

    `qirabot login` writes a real credential file under $XDG_CONFIG_HOME /
    %APPDATA%; without this, a developer who has logged in on their machine
    would leak that key into any test exercising the CLI's key-resolution
    fallback (e.g. doctor's "API key not set" assertions).
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
