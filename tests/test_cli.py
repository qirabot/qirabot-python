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
    """Inject a fake ``appium`` package so the android/ios commands import cleanly.

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
def fake_airtest(monkeypatch):
    """Inject a fake ``airtest`` package (the android/ios default engine).

    Returns the fake ``airtest.core.api`` module so tests can inspect the
    connect_device/start_app calls and the device object handed to the run.
    """
    device = MagicMock(name="airtest_device")
    api = types.ModuleType("airtest.core.api")
    api.connect_device = MagicMock(name="connect_device", return_value=device)
    api.start_app = MagicMock(name="start_app")

    # facebook-wda, used by the ios command's WDA pre-check. Defaults to a
    # reachable WDA (HTTP probe succeeds) so the happy-path tests pass.
    wda = types.ModuleType("wda")
    wda.DEBUG = False
    wda.Client = MagicMock(name="wda.Client")
    wda.Client.return_value.is_ready.return_value = True
    wda.BaseClient = MagicMock(name="wda.BaseClient")
    wda.BaseClient.return_value.is_ready.return_value = True
    wda.list_devices = MagicMock(name="wda.list_devices", return_value=[])

    for name, mod in {
        "airtest": types.ModuleType("airtest"),
        "airtest.core": types.ModuleType("airtest.core"),
        "airtest.core.api": api,
        "wda": wda,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    api.wda = wda
    return api


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
        "ios", "Send hi to honey", "--engine", "appium",
        "--bundle-id", "com.tencent.xin",
    ])
    assert result.exit_code == 0, result.output

    options = fake_appium.call_args.kwargs["options"]
    assert options.bundle_id == "com.tencent.xin"


def test_ios_without_bundle_id_sets_no_bundle(fake_appium, stub_bot):
    result = _invoke(["ios", "do something", "--engine", "appium"])
    assert result.exit_code == 0, result.output

    options = fake_appium.call_args.kwargs["options"]
    assert not hasattr(options, "bundle_id")


def test_android_app_launch_flags_are_passed_to_options(fake_appium, stub_bot):
    result = _invoke([
        "android", "Open Display settings", "--engine", "appium",
        "--device", "emulator-5554",
        "--app-package", "com.android.settings",
        "--app-activity", ".Settings",
    ])
    assert result.exit_code == 0, result.output

    options = fake_appium.call_args.kwargs["options"]
    assert options.device_name == "emulator-5554"
    assert options.app_package == "com.android.settings"
    assert options.app_activity == ".Settings"


class TestAirtestEngine:
    """android/ios default to the direct engine (adb / WDA via airtest) — no
    Appium server involved."""

    def test_android_defaults_to_airtest(self, fake_airtest, fake_appium, stub_bot):
        result = _invoke([
            "android", "Open Display settings",
            "--device", "emulator-5554",
            "--app-package", "com.android.settings",
            "--app-activity", ".Settings",
        ])
        assert result.exit_code == 0, result.output

        fake_airtest.connect_device.assert_called_once_with("Android:///emulator-5554")
        fake_airtest.start_app.assert_called_once_with("com.android.settings", ".Settings")
        # The default engine must never touch the Appium server.
        fake_appium.assert_not_called()

    def test_android_without_app_package_skips_launch(self, fake_airtest, stub_bot):
        result = _invoke(["android", "do something"])
        assert result.exit_code == 0, result.output

        fake_airtest.connect_device.assert_called_once_with("Android:///")
        fake_airtest.start_app.assert_not_called()

    def test_ios_defaults_to_wda_direct(self, fake_airtest, fake_appium, stub_bot):
        result = _invoke(["ios", "Send hi to honey", "--bundle-id", "com.tencent.xin"])
        assert result.exit_code == 0, result.output

        fake_airtest.connect_device.assert_called_once_with("iOS:///http://127.0.0.1:8100")
        # iOS launches via WDA's app_launch, never airtest's start_app (go-ios
        # breaks on iOS 17+).
        device = fake_airtest.connect_device.return_value
        device.driver.app_launch.assert_called_once_with("com.tencent.xin")
        fake_airtest.start_app.assert_not_called()
        fake_appium.assert_not_called()

    def test_ios_custom_wda_url(self, fake_airtest, stub_bot):
        result = _invoke(["ios", "do it", "--wda-url", "http://10.0.0.5:8100"])
        assert result.exit_code == 0, result.output

        fake_airtest.connect_device.assert_called_once_with("iOS:///http://10.0.0.5:8100")
        fake_airtest.connect_device.return_value.driver.app_launch.assert_not_called()

    def test_ios_wda_down_fails_before_airtest_connect(self, fake_airtest, monkeypatch):
        """A dead WDA must error out BEFORE airtest's connect: handing it a
        localhost URL triggers its go-ios/tidevice auto-launch, which downloads
        developer disk images and still fails on iOS 17+."""
        from qirabot.cli import main

        bot = MagicMock(name="bot")
        monkeypatch.setattr(main, "_make_bot", lambda *a, **k: bot)
        fake_airtest.wda.Client.return_value.is_ready.return_value = False

        result = _invoke(["ios", "do it"])

        assert result.exit_code == 1
        assert "WDA is not running" in result.output
        assert "--engine appium" in result.output
        fake_airtest.connect_device.assert_not_called()
        bot.fail.assert_called_once()

    def test_ios_wda_ready_over_usbmux_without_iproxy(self, fake_airtest, stub_bot):
        """WDA up on the device but no iproxy: the HTTP probe fails, but the
        usbmux probe must pass and the run proceed (airtest itself talks to
        local devices over usbmux, so iproxy isn't required)."""
        fake_airtest.wda.Client.return_value.is_ready.return_value = False
        usb = MagicMock(connection_type="USB", serial="00008150-X")
        fake_airtest.wda.list_devices.return_value = [usb]

        result = _invoke(["ios", "do it"])

        assert result.exit_code == 0, result.output
        fake_airtest.wda.BaseClient.assert_called_once_with("http+usbmux://00008150-X:8100")
        fake_airtest.connect_device.assert_called_once_with("iOS:///http://127.0.0.1:8100")

    def test_ios_remote_wda_down_skips_usbmux_probe(self, fake_airtest, monkeypatch):
        """A remote --wda-url is not a local USB device: no usbmux fallback,
        just the fail-fast error."""
        from qirabot.cli import main

        bot = MagicMock(name="bot")
        monkeypatch.setattr(main, "_make_bot", lambda *a, **k: bot)
        fake_airtest.wda.Client.return_value.is_ready.return_value = False

        result = _invoke(["ios", "do it", "--wda-url", "http://10.0.0.5:8100"])

        assert result.exit_code == 1
        assert "WDA is not running" in result.output
        fake_airtest.wda.list_devices.assert_not_called()
        fake_airtest.connect_device.assert_not_called()

    def test_connect_failure_reports_fail_with_hint(self, fake_airtest, monkeypatch):
        from qirabot.cli import main

        bot = MagicMock(name="bot")
        monkeypatch.setattr(main, "_make_bot", lambda *a, **k: bot)
        fake_airtest.connect_device.side_effect = RuntimeError("adb: no devices/emulators found")

        result = _invoke(["android", "do something"])

        assert result.exit_code == 1
        assert "adb devices" in result.output
        assert "--engine appium" in result.output
        bot.fail.assert_called_once()
        bot.close.assert_called_once()

    def test_missing_airtest_error_points_at_appium_engine(self, monkeypatch):
        # Simulate airtest being absent (the dev env may have it installed):
        # the default engine must fail with the install hint AND the --engine
        # appium escape hatch. (MissingDependencyError is rendered one-line by
        # main(), which CliRunner bypasses — so assert on the exception itself.)
        from qirabot.cli import main
        from qirabot.exceptions import MissingDependencyError

        def missing(module, extra=None):
            raise MissingDependencyError(
                'Install it with:  python -m pip install "qirabot[airtest]"'
            )

        monkeypatch.setattr(main, "require", missing)

        result = _invoke(["android", "do something"])

        assert result.exit_code == 1
        assert 'qirabot[airtest]' in str(result.exception)
        assert "--engine appium" in str(result.exception)


class TestDesktopAirtestEngine:
    """desktop --engine airtest: Windows-only guard, URI construction from
    --window-title/--hwnd, best-effort foreground, and setup-failure reporting."""

    @pytest.fixture
    def win_platform(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")

    def test_defaults_to_whole_desktop(self, fake_airtest, stub_bot, win_platform):
        result = _invoke(["desktop", "do it", "--engine", "airtest"])

        assert result.exit_code == 0
        fake_airtest.connect_device.assert_called_once_with("Windows:///")
        fake_airtest.connect_device.return_value.to_foreground.assert_called_once()

    def test_window_title_builds_quoted_title_re(self, fake_airtest, stub_bot, win_platform):
        result = _invoke(
            ["desktop", "do it", "--engine", "airtest", "--window-title", "原神 1.0"]
        )

        assert result.exit_code == 0
        from urllib.parse import quote

        fake_airtest.connect_device.assert_called_once_with(
            f"Windows:///?title_re={quote('原神 1.0')}"
        )

    def test_hwnd_binds_by_handle(self, fake_airtest, stub_bot, win_platform):
        result = _invoke(["desktop", "do it", "--engine", "airtest", "--hwnd", "1234"])

        assert result.exit_code == 0
        fake_airtest.connect_device.assert_called_once_with("Windows:///1234")

    def test_window_title_and_hwnd_are_mutually_exclusive(self, win_platform):
        result = _invoke(
            ["desktop", "do it", "--engine", "airtest", "--window-title", "x", "--hwnd", "1"]
        )

        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_rejected_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")

        result = _invoke(["desktop", "do it", "--engine", "airtest"])

        assert result.exit_code != 0
        assert "Windows" in result.output
        assert "pyautogui" in result.output

    def test_foreground_failure_is_ignored(self, fake_airtest, stub_bot, win_platform):
        device = fake_airtest.connect_device.return_value
        device.to_foreground.side_effect = RuntimeError("no window")

        result = _invoke(["desktop", "do it", "--engine", "airtest"])

        assert result.exit_code == 0

    def test_connect_failure_reports_fail_with_hint(self, fake_airtest, monkeypatch, win_platform):
        from qirabot.cli import main

        bot = MagicMock(name="bot")
        monkeypatch.setattr(main, "_make_bot", lambda *a, **k: bot)
        fake_airtest.connect_device.side_effect = RuntimeError("window not found")

        result = _invoke(
            ["desktop", "do it", "--engine", "airtest", "--window-title", "nope"]
        )

        assert result.exit_code == 1
        assert "--app-wait" in result.output
        bot.fail.assert_called_once()
        bot.close.assert_called_once()

    def test_missing_airtest_hint_points_at_pyautogui(self, monkeypatch, win_platform):
        # Same mechanics as the android missing-airtest test: CliRunner bypasses
        # main()'s one-line rendering, so assert on the exception itself.
        from qirabot.cli import main
        from qirabot.exceptions import MissingDependencyError

        def missing(module, extra=None):
            raise MissingDependencyError(
                'Install it with:  python -m pip install "qirabot[airtest]"'
            )

        monkeypatch.setattr(main, "require", missing)

        result = _invoke(["desktop", "do it", "--engine", "airtest"])

        assert result.exit_code == 1
        assert 'qirabot[airtest]' in str(result.exception)
        assert "drop --engine airtest" in str(result.exception)

    def test_app_launched_before_connect(self, fake_airtest, stub_bot, win_platform, monkeypatch):
        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            "qirabot.launch_app", lambda app, wait=2.0: calls.append(("launch", app))
        )
        fake_airtest.connect_device.side_effect = (
            lambda uri: calls.append(("connect", uri)) or MagicMock(name="device")
        )

        result = _invoke(
            ["desktop", "do it", "--engine", "airtest", "--app", "C:/game.exe"]
        )

        assert result.exit_code == 0
        assert [c[0] for c in calls] == ["launch", "connect"]


class TestEngineFlagValidation:
    """Engine-specific URL/device flags are rejected under the other engine
    (only when explicitly passed — defaults never trip the guard)."""

    def test_desktop_default_engine_rejects_window_title(self):
        result = _invoke(["desktop", "do it", "--window-title", "x"])

        assert result.exit_code != 0
        assert "--engine airtest" in result.output

    def test_desktop_default_engine_rejects_hwnd(self):
        result = _invoke(["desktop", "do it", "--hwnd", "1234"])

        assert result.exit_code != 0
        assert "--engine airtest" in result.output

    def test_android_airtest_rejects_appium_url(self, fake_airtest, stub_bot):
        result = _invoke(["android", "do it", "--appium-url", "http://x:4723"])

        assert result.exit_code != 0
        assert "--engine appium" in result.output

    def test_ios_airtest_rejects_appium_url(self, fake_airtest, stub_bot):
        result = _invoke(["ios", "do it", "--appium-url", "http://x:4723"])

        assert result.exit_code != 0
        assert "--engine appium" in result.output

    def test_ios_airtest_rejects_device(self, fake_airtest, stub_bot):
        result = _invoke(["ios", "do it", "--device", "iPhone 15"])

        assert result.exit_code != 0
        assert "--engine appium" in result.output

    def test_ios_appium_rejects_mjpeg_url(self, fake_appium, stub_bot):
        result = _invoke(["ios", "do it", "--engine", "appium", "--record", "--mjpeg-url", "http://x:9100"])

        assert result.exit_code != 0
        assert "--mjpeg-url" in result.output

    def test_ios_mjpeg_url_requires_record(self, fake_airtest, stub_bot):
        result = _invoke(["ios", "do it", "--mjpeg-url", "http://x:9100"])

        assert result.exit_code != 0
        assert "--record" in result.output

    def test_ios_appium_rejects_wda_url(self, fake_appium, stub_bot):
        result = _invoke(["ios", "do it", "--engine", "appium", "--wda-url", "http://x:8100"])

        assert result.exit_code != 0
        assert "--engine airtest" in result.output


class TestDeviceRecording:
    """--record on android/ios: recorder-source selection per engine (WDA MJPEG
    with its fail-fast check, adb screenrecord, Appium recording API) and the
    flag threading into _make_bot."""

    def _capture(self, monkeypatch):
        from qirabot.cli import main

        captured = {"make_bot": {}, "checked_url": None}

        def fake_make_bot(ctx, **kwargs):
            captured["make_bot"].update(kwargs)
            return MagicMock(name="bot")

        def fake_check(url):
            captured["checked_url"] = url

        monkeypatch.setattr(main, "_make_bot", fake_make_bot)
        monkeypatch.setattr(main, "_run_local", lambda *a, **k: None)
        monkeypatch.setattr(main, "_check_mjpeg_ready", fake_check)
        return captured

    def test_record_derives_mjpeg_url_from_wda_url(self, fake_airtest, monkeypatch):
        captured = self._capture(monkeypatch)

        result = _invoke(["ios", "do it", "--record"])

        assert result.exit_code == 0, result.output
        assert captured["checked_url"] == "http://127.0.0.1:9100"
        assert captured["make_bot"]["record"] is True
        assert captured["make_bot"]["record_mjpeg_url"] == "http://127.0.0.1:9100"

    def test_record_follows_wda_host(self, fake_airtest, monkeypatch):
        captured = self._capture(monkeypatch)

        result = _invoke(["ios", "do it", "--record", "--wda-url", "http://10.0.0.5:8100"])

        assert result.exit_code == 0, result.output
        assert captured["checked_url"] == "http://10.0.0.5:9100"

    def test_explicit_mjpeg_url_wins(self, fake_airtest, monkeypatch):
        captured = self._capture(monkeypatch)

        result = _invoke(["ios", "do it", "--record", "--mjpeg-url", "http://10.0.0.5:9200"])

        assert result.exit_code == 0, result.output
        assert captured["checked_url"] == "http://10.0.0.5:9200"
        assert captured["make_bot"]["record_mjpeg_url"] == "http://10.0.0.5:9200"

    def test_no_record_skips_check_and_recording(self, fake_airtest, monkeypatch):
        captured = self._capture(monkeypatch)

        result = _invoke(["ios", "do it"])

        assert result.exit_code == 0, result.output
        assert captured["checked_url"] is None
        assert captured["make_bot"]["record"] is False
        assert captured["make_bot"]["record_mjpeg_url"] == ""

    def test_android_record_uses_adb_screenrecord(self, fake_airtest, monkeypatch):
        captured = self._capture(monkeypatch)

        result = _invoke(["android", "do it", "--record"])

        assert result.exit_code == 0, result.output
        assert captured["make_bot"]["record"] is True
        assert captured["make_bot"]["record_device"] is True
        # No MJPEG involved on android — that's the iOS/WDA path.
        assert captured["checked_url"] is None

    def test_android_appium_record_threads_device_recording(self, fake_appium, monkeypatch):
        captured = self._capture(monkeypatch)

        result = _invoke(["android", "do it", "--engine", "appium", "--record"])

        assert result.exit_code == 0, result.output
        assert captured["make_bot"]["record"] is True
        assert captured["make_bot"]["record_device"] is True

    def test_ios_appium_record_threads_device_recording(self, fake_appium, monkeypatch):
        captured = self._capture(monkeypatch)

        result = _invoke(["ios", "do it", "--engine", "appium", "--record"])

        assert result.exit_code == 0, result.output
        assert captured["make_bot"]["record"] is True
        assert captured["make_bot"]["record_device"] is True

    def test_appium_recording_stopped_before_driver_quit(self, fake_appium, monkeypatch):
        # The Appium video lives in the session: bot.stop_recording() must run
        # before driver.quit() or the recording is lost.
        from qirabot.cli import main

        order = []
        bot = MagicMock(name="bot")
        bot.stop_recording.side_effect = lambda: order.append("stop_recording")
        driver = fake_appium.return_value
        driver.quit.side_effect = lambda: order.append("quit")

        monkeypatch.setattr(main, "_make_bot", lambda *a, **k: bot)
        monkeypatch.setattr(main, "_run_local", lambda *a, **k: None)

        result = _invoke(["android", "do it", "--engine", "appium", "--record"])

        assert result.exit_code == 0, result.output
        assert order == ["stop_recording", "quit"]

    def test_unreachable_stream_fails_before_task_creation(self, fake_airtest, monkeypatch):
        # The probe failing must exit with the iproxy hint and never build the
        # bot (no server task, no 300-step run that quietly recorded nothing).
        import qirabot.recording as recording_mod
        from qirabot.cli import main

        made = []
        monkeypatch.setattr(main, "_make_bot", lambda *a, **k: made.append(1) or MagicMock())
        monkeypatch.setattr(main, "_run_local", lambda *a, **k: None)
        monkeypatch.setattr(
            recording_mod, "check_mjpeg_stream",
            lambda url, timeout=5.0: f"cannot read MJPEG stream at {url} (refused)",
        )

        result = _invoke(["ios", "do it", "--record"])

        assert result.exit_code != 0
        assert "iproxy 9100 9100" in result.output
        assert made == []


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
        # 0 here made `qirabot browser ... && deploy` silently proceed on failure.
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

    def test_browser_open_failure_reports_fail(self, monkeypatch):
        from qirabot.cli import main

        bot = MagicMock(name="bot")
        bot.open.side_effect = RuntimeError("chromium launch failed")
        monkeypatch.setattr(main, "_make_bot", lambda *a, **k: bot)

        result = _invoke(["browser", "do something", "--url", "example.com"])

        assert result.exit_code == 1
        bot.fail.assert_called_once()
        bot.close.assert_called_once()

    @pytest.mark.parametrize("command", ["android", "ios"])
    def test_appium_remote_failure_reports_fail(self, fake_appium, monkeypatch, command):
        from qirabot.cli import main

        bot = MagicMock(name="bot")
        monkeypatch.setattr(main, "_make_bot", lambda *a, **k: bot)
        fake_appium.side_effect = RuntimeError("appium server unreachable")

        result = _invoke([command, "do something", "--engine", "appium"])

        assert result.exit_code == 1
        bot.fail.assert_called_once()
        bot.close.assert_called_once()

    def test_quit_error_after_success_is_not_a_failure(self, fake_appium, monkeypatch):
        # driver.quit() raising after a successful run must NOT be turned into a
        # task failure — the setup except is scoped to Remote() only.
        from qirabot.cli import main

        bot = MagicMock(name="bot")
        monkeypatch.setattr(main, "_make_bot", lambda *a, **k: bot)
        monkeypatch.setattr(main, "_run_local", lambda *a, **k: None)
        driver = MagicMock(name="driver")
        driver.quit.side_effect = RuntimeError("quit boom")
        fake_appium.return_value = driver

        _invoke(["android", "do something", "--engine", "appium"])

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

        result = _invoke(["browser", "do something"])

        assert result.exit_code == 1
        assert "Could not connect to https://x" in result.output

    def test_missing_api_key_message_is_uniform(self, monkeypatch):
        monkeypatch.delenv("QIRA_API_KEY", raising=False)

        from qirabot.cli.main import cli

        result = CliRunner().invoke(cli, ["browser", "do something"])

        assert result.exit_code == 1
        assert "Set QIRA_API_KEY or pass --api-key" in result.output


class TestHelpers:
    def test_wda_mjpeg_url_defaults(self):
        from qirabot.cli.main import _wda_mjpeg_url

        assert _wda_mjpeg_url("http://127.0.0.1:8100") == "http://127.0.0.1:9100"
        assert _wda_mjpeg_url("http://10.0.0.5:8100") == "http://10.0.0.5:9100"
        # Scheme-less values (users paste host:port) still resolve the host.
        assert _wda_mjpeg_url("10.0.0.5:8100") == "http://10.0.0.5:9100"

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

        result = _invoke(["browser", "Find the cheapest flight to Tokyo"])

        assert result.exit_code == 0, result.output
        assert captured["task_name"] == "Find the cheapest flight to Tokyo"
        assert captured["report"] is True
        assert captured["record"] is False

    def test_explicit_name_and_no_report(self, monkeypatch):
        captured = self._capture_make_bot(monkeypatch)

        result = _invoke(["browser", "do it", "--name", "smoke-test", "--no-report", "--record"])

        assert result.exit_code == 0, result.output
        assert captured["task_name"] == "smoke-test"
        assert captured["report"] is False
        assert captured["record"] is True


class TestMobileSplit:
    """`mobile` was split into `android`/`ios`; cross-platform flags are now
    rejected by click itself as unknown options instead of hand-rolled guards."""

    def test_mobile_command_is_gone(self):
        from qirabot.cli.main import cli

        ctx = click.Context(cli)
        commands = cli.list_commands(ctx)
        assert "android" in commands
        assert "ios" in commands
        assert "mobile" not in commands
        assert cli.get_command(ctx, "mobile") is None

    def test_ios_rejects_android_flags(self, fake_appium, stub_bot):
        result = _invoke(["ios", "do it", "--app-package", "com.x"])

        assert result.exit_code != 0
        assert "--app-package" in result.output

    def test_android_rejects_bundle_id(self, fake_appium, stub_bot):
        result = _invoke(["android", "do it", "--bundle-id", "com.x"])

        assert result.exit_code != 0
        assert "--bundle-id" in result.output


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


class TestBrowserCommand:
    def test_browser_is_canonical_and_browse_is_gone(self):
        from qirabot.cli.main import cli

        ctx = click.Context(cli)
        commands = cli.list_commands(ctx)
        assert "browser" in commands
        # The old verb name must no longer resolve after the rename.
        assert "browse" not in commands
        assert cli.get_command(ctx, "browse") is None

    def test_browser_runs(self, stub_bot):
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


class TestDoctor:
    """doctor is pure wiring around probes — stub the probes, assert the verdict."""

    def _run(
        self, monkeypatch, *, has=(), chromium=None, key=True, server_ok=True, display=True
    ):
        """Invoke doctor with stubbed probes; returns the click result."""
        from qirabot.cli import main

        monkeypatch.setattr(main, "_has_module", lambda m: m.split(".")[0] in has)
        monkeypatch.setattr(main, "_chromium_status", lambda: chromium)
        monkeypatch.setattr(main, "_display_available", lambda: display)
        transport = MagicMock(name="transport")
        if not server_ok:
            transport.request.side_effect = RuntimeError("401 bad key")
        monkeypatch.setattr(main, "_transport", lambda ctx: transport)

        monkeypatch.delenv("QIRA_API_KEY", raising=False)
        args = (["--api-key", "qk_test"] if key else []) + ["doctor"]
        return CliRunner().invoke(main.cli, args)

    @staticmethod
    def _flat(result):
        """Rich wraps long lines at the console width; normalize whitespace so
        substring assertions don't break on a wrap point."""
        return " ".join(result.output.split())

    def test_ready_when_key_and_one_backend(self, monkeypatch):
        result = self._run(monkeypatch, has={"playwright"}, chromium="ready")

        assert result.exit_code == 0, result.output
        assert "Ready" in self._flat(result)

    def test_nothing_installed_exits_1_with_hints(self, monkeypatch):
        result = self._run(monkeypatch, key=False)

        out = self._flat(result)
        assert result.exit_code == 1
        assert "API key not set" in out
        assert 'python -m pip install "qirabot[browser]" && playwright install chromium' in out
        # Selenium is not an extra — the hint must be a plain pip install.
        assert "python -m pip install selenium" in out
        assert "qirabot[selenium]" not in out
        assert "Not ready" in out

    def test_playwright_without_chromium_is_not_ready(self, monkeypatch):
        """An importable playwright with no browser download can't run bot.open();
        doctor must point at the missing `playwright install chromium` step."""
        result = self._run(monkeypatch, has={"playwright"}, chromium="no-browser")

        out = self._flat(result)
        assert result.exit_code == 1
        assert "playwright install chromium" in out

    def test_no_display_notes_headless_fallback_but_stays_ready(self, monkeypatch):
        """A display-less Linux box is still a working browser environment
        (open() falls back to headless) — doctor informs, not fails."""
        result = self._run(
            monkeypatch, has={"playwright"}, chromium="ready", display=False
        )

        out = self._flat(result)
        assert result.exit_code == 0, result.output
        assert "fall back to headless" in out

    def test_display_available_prints_no_headless_note(self, monkeypatch):
        result = self._run(monkeypatch, has={"playwright"}, chromium="ready")

        assert "fall back to headless" not in self._flat(result)

    def test_chromium_missing_system_libs_is_not_ready(self, monkeypatch):
        """A downloaded Chromium whose shared libraries don't resolve (bare Linux
        server) fails at launch; the fix is install-deps, not a re-download."""
        result = self._run(monkeypatch, has={"playwright"}, chromium="no-libs")

        out = self._flat(result)
        assert result.exit_code == 1
        assert "sudo playwright install-deps chromium" in out
        assert "system libraries are missing" in out

    def test_server_rejection_is_a_problem(self, monkeypatch):
        result = self._run(
            monkeypatch, has={"pyautogui"}, chromium=None, server_ok=False
        )

        out = self._flat(result)
        assert result.exit_code == 1
        assert "401 bad key" in out

    def _run_real_transport(self, monkeypatch, *cli_args):
        """Invoke doctor with probes stubbed but _transport left real, so the
        Transport construction (and its timeout) can be asserted."""
        from qirabot.cli import main

        monkeypatch.setattr(main, "_has_module", lambda m: False)
        monkeypatch.setattr(main, "_chromium_status", lambda: None)
        monkeypatch.setattr(main, "_display_available", lambda: True)
        transport_cls = MagicMock(name="Transport")
        monkeypatch.setattr(main, "Transport", transport_cls)

        monkeypatch.delenv("QIRA_API_KEY", raising=False)
        CliRunner().invoke(main.cli, [*cli_args, "--api-key", "qk_test", "doctor"])
        return transport_cls

    def test_server_check_uses_short_timeout_by_default(self, monkeypatch):
        """doctor is a diagnostic — against an unreachable server the 120s task
        default reads as a hang, so the server check drops to 10s."""
        transport_cls = self._run_real_transport(monkeypatch)

        assert transport_cls.call_args.kwargs["timeout"] == 10.0

    def test_server_check_respects_explicit_timeout(self, monkeypatch):
        transport_cls = self._run_real_transport(monkeypatch, "--timeout", "3")

        assert transport_cls.call_args.kwargs["timeout"] == 3.0

    def test_other_backend_alone_is_ready(self, monkeypatch):
        """The default path (browser) is a recommendation, not a requirement —
        an Airtest-only environment is a valid, ready setup."""
        result = self._run(monkeypatch, has={"airtest"}, chromium=None)

        assert result.exit_code == 0, result.output
        assert "Ready" in self._flat(result)
