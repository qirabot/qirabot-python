"""Tests for CLI option wiring (no network, no real Appium/devices)."""

import sys
import types
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner


class _FakeOptions:
    """Stand-in for XCUITestOptions/UiAutomator2Options that records attrs set."""


@pytest.fixture
def fake_appium(monkeypatch):
    """Inject a fake ``appium`` package so the mobile command imports cleanly.

    Returns the MagicMock used for ``webdriver.Remote`` so tests can inspect the
    options object the command built and handed to it.
    """
    remote = MagicMock(name="Remote", return_value=MagicMock(name="driver"))

    appium = types.ModuleType("appium")
    webdriver = types.ModuleType("appium.webdriver")
    webdriver.Remote = remote
    appium.webdriver = webdriver

    options_pkg = types.ModuleType("appium.options")
    ios_mod = types.ModuleType("appium.options.ios")
    ios_mod.XCUITestOptions = _FakeOptions
    android_mod = types.ModuleType("appium.options.android")
    android_mod.UiAutomator2Options = _FakeOptions

    for name, mod in {
        "appium": appium,
        "appium.webdriver": webdriver,
        "appium.options": options_pkg,
        "appium.options.ios": ios_mod,
        "appium.options.android": android_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    return remote


@pytest.fixture
def stub_bot(monkeypatch):
    """Bypass task creation / AI run so the command exercises only wiring."""
    from qirabot.cli import main

    monkeypatch.setattr(main, "_make_bot", lambda *a, **k: MagicMock(name="bot"))
    monkeypatch.setattr(main, "_run_local", lambda *a, **k: None)


def _invoke(args):
    from qirabot.cli.main import cli

    return CliRunner().invoke(cli, ["--api-key", "qk_test", *args])


def test_ios_bundle_id_is_passed_to_options(fake_appium, stub_bot):
    result = _invoke([
        "mobile", "Send hi to honey",
        "--platform", "ios",
        "--bundle-id", "com.tencent.xin",
    ])
    assert result.exit_code == 0, result.output

    options = fake_appium.call_args.kwargs["options"]
    assert options.bundle_id == "com.tencent.xin"


def test_ios_without_bundle_id_sets_no_bundle(fake_appium, stub_bot):
    result = _invoke(["mobile", "do something", "--platform", "ios"])
    assert result.exit_code == 0, result.output

    options = fake_appium.call_args.kwargs["options"]
    assert not hasattr(options, "bundle_id")


class TestRunLocalAbort:
    """A Ctrl+C during bot.ai() must be reported, never left for the caller's
    finally:bot.close() to complete the task as success. KeyboardInterrupt is a
    BaseException, so this guards the `except Exception` gap that previously let
    interrupted runs land as 'succeeded'."""

    def _stub_bot(self):
        bot = MagicMock(name="bot")
        bot.task_id = "t"
        return bot

    def test_keyboardinterrupt_reports_cancel_and_exits_130(self):
        from qirabot.cli.main import _run_local

        bot = self._stub_bot()
        bot.ai.side_effect = KeyboardInterrupt()

        with pytest.raises(SystemExit) as exc:
            _run_local(bot, object(), "send a message", max_steps=20)

        assert exc.value.code == 130
        # Ctrl+C is a deliberate cancel, not a failure.
        bot.cancel.assert_called_once()
        bot.fail.assert_not_called()
        # _run_local must not close the bot — that's the command's finally.
        bot.close.assert_not_called()

    def test_exception_still_reports_failure_and_exits_1(self):
        from qirabot.cli.main import _run_local

        bot = self._stub_bot()
        bot.ai.side_effect = RuntimeError("boom")

        with pytest.raises(SystemExit) as exc:
            _run_local(bot, object(), "send a message", max_steps=20)

        assert exc.value.code == 1
        bot.fail.assert_called_once_with("boom")

    def test_failed_result_reports_failure(self):
        from qirabot.cli.main import _run_local
        from qirabot.client import RunResult

        bot = self._stub_bot()
        bot.ai.return_value = RunResult(success=False, output="max steps reached")

        _run_local(bot, object(), "send a message", max_steps=20)

        bot.fail.assert_called_once_with("max steps reached")

    def test_success_result_does_not_fail(self):
        from qirabot.cli.main import _run_local
        from qirabot.client import RunResult

        bot = self._stub_bot()
        bot.ai.return_value = RunResult(success=True, output="done")

        _run_local(bot, object(), "send a message", max_steps=20)

        bot.fail.assert_not_called()
