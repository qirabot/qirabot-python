"""Tests for CLI option wiring (no network, no real Appium/devices)."""

import sys
import types
from unittest.mock import MagicMock

import click
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

    def test_failed_result_reports_failure_and_exits_1(self):
        # A failed run must exit non-zero so scripts/CI can detect it — exiting
        # 0 here made `qirabot browse ... && deploy` silently proceed on failure.
        from qirabot.cli.main import _run_local
        from qirabot.client import RunResult

        bot = self._stub_bot()
        bot.ai.return_value = RunResult(success=False, output="max steps reached")

        with pytest.raises(SystemExit) as exc:
            _run_local(bot, object(), "send a message", max_steps=20)

        assert exc.value.code == 1
        bot.fail.assert_called_once_with("max steps reached")

    def test_success_result_does_not_fail(self):
        from qirabot.cli.main import _run_local
        from qirabot.client import RunResult

        bot = self._stub_bot()
        bot.ai.return_value = RunResult(success=True, output="done")

        _run_local(bot, object(), "send a message", max_steps=20)

        bot.fail.assert_not_called()


class TestSetupFailureReporting:
    """A failure during setup (bot.open / Appium Remote) — after the task is
    created but before _run_local takes over reporting — must be recorded as a
    failure, never left for the command's finally:bot.close() to complete as
    succeeded."""

    def test_browse_open_failure_reports_fail(self, monkeypatch):
        from qirabot.cli import main

        bot = MagicMock(name="bot")
        bot.open.side_effect = RuntimeError("chromium launch failed")
        monkeypatch.setattr(main, "_make_bot", lambda *a, **k: bot)

        result = _invoke(["browse", "do something", "--url", "example.com"])

        assert result.exit_code == 1
        bot.fail.assert_called_once()
        bot.close.assert_called_once()

    def test_mobile_remote_failure_reports_fail(self, fake_appium, monkeypatch):
        from qirabot.cli import main

        bot = MagicMock(name="bot")
        monkeypatch.setattr(main, "_make_bot", lambda *a, **k: bot)
        fake_appium.side_effect = RuntimeError("appium server unreachable")

        result = _invoke(["mobile", "do something"])

        assert result.exit_code == 1
        bot.fail.assert_called_once()
        bot.close.assert_called_once()

    def test_mobile_quit_error_after_success_is_not_a_failure(self, fake_appium, monkeypatch):
        # driver.quit() raising after a successful run must NOT be turned into a
        # task failure — the setup except is scoped to Remote() only.
        from qirabot.cli import main

        bot = MagicMock(name="bot")
        monkeypatch.setattr(main, "_make_bot", lambda *a, **k: bot)
        monkeypatch.setattr(main, "_run_local", lambda *a, **k: None)
        driver = MagicMock(name="driver")
        driver.quit.side_effect = RuntimeError("quit boom")
        fake_appium.return_value = driver

        _invoke(["mobile", "do something"])

        bot.fail.assert_not_called()
        bot.close.assert_called_once()


class TestEntryPoint:
    def test_main_loads_dotenv_before_parsing(self, monkeypatch):
        """main() must load .env before click parses options, so envvar
        fallbacks (QIRA_API_KEY etc.) can pick up values from the file."""
        from qirabot.cli import main as cli_main

        called = []
        monkeypatch.setattr(cli_main, "load_dotenv", lambda: called.append(True))
        monkeypatch.setattr(sys, "argv", ["qirabot", "--help"])

        with pytest.raises(SystemExit) as exc:
            cli_main.main()

        assert exc.value.code == 0
        assert called == [True]

    def test_transport_error_from_readonly_command_prints_one_line(self, monkeypatch, capsys):
        """task/screenshot/models call the server without _make_bot/_run_local's
        handling; main() must turn escaping SDK errors into a one-line message
        instead of a traceback."""
        from qirabot.cli import main as cli_main
        from qirabot.exceptions import QirabotConnectionError

        t = MagicMock(name="transport")
        t.request.side_effect = QirabotConnectionError("Could not connect to http://x")
        monkeypatch.setattr(cli_main, "_transport", lambda ctx: t)
        monkeypatch.setattr(cli_main, "load_dotenv", lambda: False)
        monkeypatch.setattr(sys, "argv", ["qirabot", "--api-key", "qk", "models"])

        with pytest.raises(SystemExit) as exc:
            cli_main.main()

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "Could not connect to http://x" in err
        assert "Traceback" not in err


class TestMakeBotErrors:
    def test_connection_error_prints_transport_message(self, monkeypatch):
        """No string-sniffing: the QirabotConnectionError message from the
        transport (already actionable) is printed verbatim, exit code 1."""
        import qirabot
        from qirabot.exceptions import QirabotConnectionError

        def boom(**kwargs):
            raise QirabotConnectionError("Could not connect to https://x. Check QIRA_BASE_URL.")

        monkeypatch.setattr(qirabot, "Qirabot", boom)

        result = _invoke(["browse", "do something"])

        assert result.exit_code == 1
        assert "Could not connect to https://x" in result.output

    def test_missing_api_key_message_is_uniform(self, monkeypatch):
        monkeypatch.delenv("QIRA_API_KEY", raising=False)

        from qirabot.cli.main import cli

        result = CliRunner().invoke(cli, ["browse", "do something"])

        assert result.exit_code == 1
        assert "Set QIRA_API_KEY or pass --api-key" in result.output


class TestHelpers:
    def test_default_task_name_derives_and_truncates(self):
        from qirabot.cli.main import _default_task_name

        assert _default_task_name("Click login") == "Click login"
        # first non-blank line, stripped
        assert _default_task_name("  \n  Open the menu\nthen tap Save") == "Open the menu"
        # capped at 60 chars
        assert _default_task_name("x" * 100) == "x" * 60
        # blank instruction falls back to a stable default
        assert _default_task_name("   \n  ") == "cli"

    def test_img_ext_detects_formats(self):
        from qirabot.cli.main import _img_ext

        assert _img_ext(b"\xff\xd8\xff\xe0 jpeg body") == "jpg"
        assert _img_ext(b"\x89PNG\r\n\x1a\n png body") == "png"
        assert _img_ext(b"not an image") == "bin"


class TestRunOptionWiring:
    """--name derivation and --report/--record are threaded to _make_bot."""

    def _capture_make_bot(self, monkeypatch):
        from qirabot.cli import main

        captured = {}

        def fake_make_bot(ctx, **kwargs):
            captured.update(kwargs)
            return MagicMock(name="bot")

        monkeypatch.setattr(main, "_make_bot", fake_make_bot)
        monkeypatch.setattr(main, "_run_local", lambda *a, **k: None)
        return captured

    def test_name_defaults_to_instruction(self, monkeypatch):
        captured = self._capture_make_bot(monkeypatch)

        result = _invoke(["browse", "Find the cheapest flight to Tokyo"])

        assert result.exit_code == 0, result.output
        assert captured["task_name"] == "Find the cheapest flight to Tokyo"
        assert captured["report"] is True
        assert captured["record"] is False

    def test_explicit_name_and_no_report(self, monkeypatch):
        captured = self._capture_make_bot(monkeypatch)

        result = _invoke(["browse", "do it", "--name", "smoke-test", "--no-report", "--record"])

        assert result.exit_code == 0, result.output
        assert captured["task_name"] == "smoke-test"
        assert captured["report"] is False
        assert captured["record"] is True


class TestMobileCrossPlatformValidation:
    def test_ios_with_android_flags_errors(self, fake_appium, stub_bot):
        result = _invoke(["mobile", "do it", "--platform", "ios", "--app-package", "com.x"])

        assert result.exit_code != 0
        assert "Android-only" in result.output

    def test_android_with_bundle_id_errors(self, fake_appium, stub_bot):
        result = _invoke(["mobile", "do it", "--platform", "android", "--bundle-id", "com.x"])

        assert result.exit_code != 0
        assert "iOS-only" in result.output


class TestScreenshotDownload:
    def _stub_transport(self, monkeypatch):
        from qirabot.cli import main

        t = MagicMock(name="transport")
        t.get_bytes.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
        monkeypatch.setattr(main, "_transport", lambda ctx: t)
        return main

    def test_saves_default_filename_by_magic_bytes(self, monkeypatch):
        import os

        main = self._stub_transport(monkeypatch)

        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(main.cli, ["--api-key", "qk", "screenshot", "abc123"])
            assert result.exit_code == 0, result.output
            assert os.path.exists("screenshot-abc123.png")

    def test_refuses_to_overwrite_existing_file(self, monkeypatch):
        main = self._stub_transport(monkeypatch)

        runner = CliRunner()
        with runner.isolated_filesystem():
            with open("screenshot-abc123.png", "wb") as f:
                f.write(b"old")

            result = runner.invoke(main.cli, ["--api-key", "qk", "screenshot", "abc123"])

            assert result.exit_code == 1
            assert "already exists" in result.output
            with open("screenshot-abc123.png", "rb") as f:
                assert f.read() == b"old"

    def test_force_overwrites_existing_file(self, monkeypatch):
        main = self._stub_transport(monkeypatch)

        runner = CliRunner()
        with runner.isolated_filesystem():
            with open("screenshot-abc123.png", "wb") as f:
                f.write(b"old")

            result = runner.invoke(
                main.cli, ["--api-key", "qk", "screenshot", "abc123", "--force"]
            )

            assert result.exit_code == 0, result.output
            with open("screenshot-abc123.png", "rb") as f:
                assert f.read().startswith(b"\x89PNG")


class TestBrowserAlias:
    def test_browser_resolves_to_browse_and_stays_out_of_help(self):
        from qirabot.cli.main import cli

        ctx = click.Context(cli)
        assert cli.get_command(ctx, "browser") is cli.get_command(ctx, "browse")
        # The alias must not show up as a separate command in --help.
        assert "browser" not in cli.list_commands(ctx)

    def test_browser_alias_runs(self, stub_bot):
        result = _invoke(["browser", "do something"])

        assert result.exit_code == 0, result.output


class TestDesktopKeyCheckBeforeAppLaunch:
    def test_missing_key_fails_before_launching_app(self, monkeypatch):
        """A missing API key must fail before the --app side effect — the old
        order launched the app first and only then errored out."""
        import qirabot

        monkeypatch.delenv("QIRA_API_KEY", raising=False)
        monkeypatch.setitem(sys.modules, "pyautogui", types.ModuleType("pyautogui"))
        launch = MagicMock(name="launch_app")
        monkeypatch.setattr(qirabot, "launch_app", launch)

        from qirabot.cli.main import cli

        result = CliRunner().invoke(cli, ["desktop", "do it", "--app", "Notes"])

        assert result.exit_code == 1
        assert "Set QIRA_API_KEY or pass --api-key" in result.output
        launch.assert_not_called()
