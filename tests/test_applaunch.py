"""Tests for the cross-platform launch_app helper."""

from unittest.mock import MagicMock

import pytest

from qirabot import _applaunch
from qirabot._applaunch import launch_app


@pytest.fixture
def no_wait(monkeypatch):
    """Skip the post-launch sleep so tests are instant."""
    monkeypatch.setattr(_applaunch.time, "sleep", lambda _s: None)


@pytest.fixture
def run_spy(monkeypatch):
    spy = MagicMock()
    monkeypatch.setattr(_applaunch.subprocess, "run", spy)
    return spy


def _set_platform(monkeypatch, name):
    monkeypatch.setattr(_applaunch.platform, "system", lambda: name)


class TestMacOS:
    def test_app_name_uses_open_dash_a(self, monkeypatch, run_spy, no_wait):
        _set_platform(monkeypatch, "Darwin")
        launch_app("WeChat")
        assert run_spy.call_args[0][0] == ["open", "-a", "WeChat"]

    def test_bundle_id_uses_open_dash_b(self, monkeypatch, run_spy, no_wait):
        _set_platform(monkeypatch, "Darwin")
        launch_app("com.tencent.xinWeChat")
        assert run_spy.call_args[0][0] == ["open", "-b", "com.tencent.xinWeChat"]

    def test_app_path_uses_open_dash_a(self, monkeypatch, run_spy, no_wait):
        _set_platform(monkeypatch, "Darwin")
        launch_app("/Applications/WeChat.app")
        assert run_spy.call_args[0][0] == ["open", "-a", "/Applications/WeChat.app"]

    def test_launch_failure_raises_runtime_error(self, monkeypatch, no_wait):
        import subprocess as sp

        _set_platform(monkeypatch, "Darwin")
        monkeypatch.setattr(
            _applaunch.subprocess, "run",
            MagicMock(side_effect=sp.CalledProcessError(1, "open", stderr="Unable to find application")),
        )
        with pytest.raises(RuntimeError, match="Unable to find application"):
            launch_app("Nope")


class TestWindows:
    def test_existing_path_uses_startfile(self, monkeypatch, no_wait):
        _set_platform(monkeypatch, "Windows")
        monkeypatch.setattr(_applaunch.os.path, "exists", lambda _p: True)
        startfile = MagicMock()
        # os.startfile only exists on Windows; inject it for the test.
        monkeypatch.setattr(_applaunch.os, "startfile", startfile, raising=False)
        launch_app(r"C:\\Program Files\\App\\app.exe")
        startfile.assert_called_once_with(r"C:\\Program Files\\App\\app.exe")

    def test_uwp_app_uses_explorer(self, monkeypatch, run_spy, no_wait):
        _set_platform(monkeypatch, "Windows")
        monkeypatch.setattr(_applaunch.os.path, "exists", lambda _p: False)
        launch_app("Microsoft.WindowsCalculator_8wekyb3d8bbwe!App")
        cmd = run_spy.call_args[0][0]
        assert cmd[0] == "explorer.exe"
        assert cmd[1].startswith("shell:AppsFolder\\")

    def test_registered_name_uses_start(self, monkeypatch, run_spy, no_wait):
        _set_platform(monkeypatch, "Windows")
        monkeypatch.setattr(_applaunch.os.path, "exists", lambda _p: False)
        launch_app("notepad")
        assert run_spy.call_args[0][0] == ["cmd", "/c", "start", "", "notepad"]


class TestLinux:
    def test_uses_which_and_popen(self, monkeypatch, no_wait):
        _set_platform(monkeypatch, "Linux")
        monkeypatch.setattr(_applaunch.shutil, "which", lambda _a: "/usr/bin/gedit")
        popen = MagicMock()
        monkeypatch.setattr(_applaunch.subprocess, "Popen", popen)
        launch_app("gedit")
        popen.assert_called_once_with(["/usr/bin/gedit"])


def test_wait_zero_skips_sleep(monkeypatch, run_spy):
    _set_platform(monkeypatch, "Darwin")
    sleep = MagicMock()
    monkeypatch.setattr(_applaunch.time, "sleep", sleep)
    launch_app("WeChat", wait=0)
    sleep.assert_not_called()
