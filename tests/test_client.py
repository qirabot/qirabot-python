"""Tests for Qirabot client, StepResult, and RunResult."""

from unittest.mock import MagicMock

import pytest

from qirabot.adapters.base import DeviceAdapter, DeviceInfo, ScreenshotConfig
from qirabot.client import Qirabot, StepResult, RunResult, _annotate_screenshot
from qirabot.exceptions import AuthenticationError


class _SettleFakeAdapter(DeviceAdapter):
    """Minimal adapter with a non-zero settle default, for client wiring tests."""

    _SETTLE_SECONDS = 0.6

    def __init__(self):
        pass

    @classmethod
    def accepts(cls, target):
        return False

    def screenshot(self, config=None):
        return b""

    def click(self, x, y):
        pass

    def double_click(self, x, y):
        pass

    def type_text(self, x, y, text):
        pass

    def press_key(self, key):
        pass

    def scroll(self, x, y, direction, distance):
        pass

    def device_info(self):
        return DeviceInfo(platform="test", width=100, height=100)


class TestStepResult:
    def test_from_dict(self):
        data = {
            "actionType": "click",
            "params": {"x": 100, "y": 200},
            "output": "clicked",
            "finished": False,
            "decision": "clicking the button",
            "inputTokens": 500,
            "outputTokens": 50,
        }
        s = StepResult.from_dict(data, step=3)
        assert s.step == 3
        assert s.action_type == "click"
        assert s.params == {"x": 100, "y": 200}
        assert s.output == "clicked"
        assert s.finished is False
        assert s.decision == "clicking the button"
        assert s.input_tokens == 500
        assert s.output_tokens == 50

    def test_from_dict_empty(self):
        s = StepResult.from_dict({}, step=1)
        assert s.step == 1
        assert s.action_type == ""
        assert s.params == {}
        assert s.output == ""
        assert s.finished is False

    def test_from_dict_finished(self):
        s = StepResult.from_dict({"finished": True, "output": "done"}, step=5)
        assert s.finished is True
        assert s.output == "done"


class TestRunResult:
    def test_success(self):
        r = RunResult(success=True, output="completed", steps=[])
        assert r.success is True
        assert r.output == "completed"

    def test_failure(self):
        r = RunResult(success=False, output="max steps reached")
        assert r.success is False
        assert r.steps == []


class TestAiLoopFinish:
    """The done action's success flag drives RunResult.success: a clean run that
    concludes the goal is unreachable (success:false) is a failure, not a pass.
    The top-level success only means the step committed, so it stays true here."""

    def _bot_returning(self, done_result):
        bot = Qirabot(api_key="k", task_id="t")
        bot._get_adapter = lambda target: _SettleFakeAdapter()
        bot._record_step = lambda *a, **k: None
        bot._post_act_retrying = lambda **kw: done_result
        return bot

    def test_done_success_true_yields_success(self):
        bot = self._bot_returning({
            "success": True, "finished": True, "actionType": "done",
            "params": {"result": "all good", "success": True},
            "output": "all good",
        })
        result = bot.ai(object(), "do thing", max_steps=3)
        assert result.success is True
        assert result.output == "all good"
        bot.close()

    def test_done_success_false_yields_failure(self):
        bot = self._bot_returning({
            "success": True, "finished": True, "actionType": "done",
            "params": {"result": "blocked: login wall", "success": False},
            "output": "blocked: login wall",
        })
        result = bot.ai(object(), "do thing", max_steps=3)
        assert result.success is False
        assert result.output == "blocked: login wall"
        bot.close()

    def test_done_missing_flag_defaults_success(self):
        bot = self._bot_returning({
            "success": True, "finished": True, "actionType": "done",
            "params": {"result": "legacy"},
            "output": "legacy",
        })
        result = bot.ai(object(), "do thing", max_steps=3)
        assert result.success is True
        bot.close()


class TestQirabotInit:
    # task_id="t" short-circuits the /tasks/create HTTP call so these unit
    # tests don't need a live server. Each test below exercises a non-task
    # config concern (base_url, env vars, screenshot dir) where the task ID
    # is incidental.

    def test_default_base_url(self):
        bot = Qirabot(api_key="test_key", task_id="t")
        assert bot._transport._base_url == "https://app.qirabot.com"
        bot.close()

    def test_custom_base_url(self):
        bot = Qirabot(api_key="test_key", base_url="http://localhost:8080", task_id="t")
        assert bot._transport._base_url == "http://localhost:8080"
        bot.close()

    def test_env_api_key(self, monkeypatch):
        monkeypatch.setenv("QIRA_API_KEY", "env_key")
        bot = Qirabot(task_id="t")
        assert bot._transport._api_key == "env_key"
        bot.close()

    def test_env_base_url(self, monkeypatch):
        monkeypatch.setenv("QIRA_BASE_URL", "http://env-host:9090")
        bot = Qirabot(api_key="k", task_id="t")
        assert bot._transport._base_url == "http://env-host:9090"
        bot.close()

    def test_report_dir_root_from_env(self, monkeypatch):
        monkeypatch.setenv("QIRA_REPORT_DIR", "/tmp/shots")
        bot = Qirabot(api_key="k", task_id="t")
        # env sets only the root; date/run subdirs are appended automatically.
        assert str(bot._report_dir).startswith("/tmp/shots/")
        bot.close()

    def test_report_dir_param_overrides_env(self, monkeypatch):
        monkeypatch.setenv("QIRA_REPORT_DIR", "/tmp/shots")
        bot = Qirabot(api_key="k", report_dir="./local", task_id="t")
        assert str(bot._report_dir).startswith("local/")
        bot.close()

    def test_settle_seconds_default_none(self):
        bot = Qirabot(api_key="k", task_id="t")
        assert bot._settle_seconds is None
        bot.close()

    def test_settle_seconds_param(self):
        bot = Qirabot(api_key="k", task_id="t", settle_seconds=0.3)
        assert bot._settle_seconds == 0.3
        bot.close()

    def test_settle_seconds_zero_allowed(self):
        bot = Qirabot(api_key="k", task_id="t", settle_seconds=0)
        assert bot._settle_seconds == 0
        bot.close()

    def test_settle_seconds_negative_rejected(self):
        with pytest.raises(ValueError, match="settle_seconds must be >= 0"):
            Qirabot(api_key="k", task_id="t", settle_seconds=-1)

    def test_settle_seconds_from_env(self, monkeypatch):
        monkeypatch.setenv("QIRA_SETTLE_SECONDS", "1.5")
        bot = Qirabot(api_key="k", task_id="t")
        assert bot._settle_seconds == 1.5
        bot.close()

    def test_settle_seconds_param_overrides_env(self, monkeypatch):
        monkeypatch.setenv("QIRA_SETTLE_SECONDS", "1.5")
        bot = Qirabot(api_key="k", task_id="t", settle_seconds=0.2)
        assert bot._settle_seconds == 0.2
        bot.close()

    def test_settle_seconds_env_invalid_rejected(self, monkeypatch):
        monkeypatch.setenv("QIRA_SETTLE_SECONDS", "soon")
        with pytest.raises(ValueError, match="QIRA_SETTLE_SECONDS must be a number"):
            Qirabot(api_key="k", task_id="t")

    def test_settle_seconds_applied_to_adapter(self, monkeypatch):
        import qirabot.client as client_mod

        adapter = _SettleFakeAdapter()
        monkeypatch.setattr(client_mod.auto, "detect", lambda target: adapter)
        bot = Qirabot(api_key="k", task_id="t", settle_seconds=0.25)
        got = bot._get_adapter(object())
        assert got is adapter
        assert adapter.settle_seconds == 0.25
        bot.close()

    def test_settle_seconds_none_keeps_adapter_default(self, monkeypatch):
        import qirabot.client as client_mod

        adapter = _SettleFakeAdapter()
        monkeypatch.setattr(client_mod.auto, "detect", lambda target: adapter)
        bot = Qirabot(api_key="k", task_id="t")
        bot._get_adapter(object())
        assert adapter._settle_override is None
        assert adapter.settle_seconds == adapter._SETTLE_SECONDS
        bot.close()


class TestQirabotMissingApiKey:
    """A missing API key is a local config error, so the constructor must fail
    fast with an actionable message — before building a transport or making the
    /tasks/create round-trip that would otherwise bounce back as an opaque 401."""

    def test_missing_key_fails_fast_before_network(self, monkeypatch):
        import qirabot.client as client_mod

        monkeypatch.delenv("QIRA_API_KEY", raising=False)
        built = []
        monkeypatch.setattr(client_mod, "Transport", lambda **kw: built.append(kw))

        with pytest.raises(AuthenticationError, match="No API key provided"):
            client_mod.Qirabot()

        # No transport constructed → no network round-trip to discover the error.
        assert built == []

    def test_missing_key_has_actionable_code(self, monkeypatch):
        monkeypatch.delenv("QIRA_API_KEY", raising=False)
        with pytest.raises(AuthenticationError) as exc_info:
            Qirabot()
        assert exc_info.value.code == "auth.api_key_missing"

    def test_empty_string_key_rejected(self, monkeypatch):
        monkeypatch.delenv("QIRA_API_KEY", raising=False)
        with pytest.raises(AuthenticationError):
            Qirabot(api_key="")


class TestQirabotContextManager:
    def test_enter_exit(self):
        bot = Qirabot(api_key="k", task_id="t")
        with bot as b:
            assert b is bot
        # close should not raise on second call
        bot.close()

    def test_exit_with_exception_reports_failure(self):
        bot = _owned_bot_with_mock_transport()
        with pytest.raises(ValueError):
            with bot:
                raise ValueError("boom")
        # Failure reported, and the success-complete from close() is suppressed.
        _assert_single_complete(bot._transport, status="failed", error="boom")

    def test_exit_with_keyboardinterrupt_reports_cancel(self):
        bot = _owned_bot_with_mock_transport()
        with pytest.raises(KeyboardInterrupt):
            with bot:
                raise KeyboardInterrupt()
        # Ctrl+C is a deliberate cancel, not a failure.
        _assert_single_complete(bot._transport, status="cancelled", error="aborted by user")


def _owned_bot_with_mock_transport():
    """A bot that owns its task (not external) with a mocked transport, so
    close()/fail() exercise the real /complete HTTP path against the mock."""
    bot = Qirabot(api_key="k", task_id="t")
    bot._external_task = False
    bot._transport = MagicMock()
    return bot


def _complete_calls(transport):
    return [
        c for c in transport.post.call_args_list
        if c.args and str(c.args[0]).endswith("/complete")
    ]


def _assert_single_complete(transport, *, status=None, error=None):
    calls = _complete_calls(transport)
    assert len(calls) == 1, f"expected exactly one /complete, got {calls}"
    body = calls[0].kwargs.get("json_data")
    if status is None:
        assert not body, f"expected success-complete with no body, got {body}"
    else:
        assert body == {"status": status, "errorMessage": error}


class TestQirabotTerminalStatus:
    def test_close_completes_as_success(self):
        bot = _owned_bot_with_mock_transport()
        bot.close()
        _assert_single_complete(bot._transport)

    def test_fail_reports_failed_status(self):
        bot = _owned_bot_with_mock_transport()
        bot.fail("screenshot encode error")
        _assert_single_complete(bot._transport, status="failed", error="screenshot encode error")

    def test_close_after_fail_does_not_override(self):
        bot = _owned_bot_with_mock_transport()
        bot.fail("boom")
        bot.close()
        # close() must not post a second (success) completion.
        _assert_single_complete(bot._transport, status="failed", error="boom")

    def test_fail_is_idempotent(self):
        bot = _owned_bot_with_mock_transport()
        bot.fail("first")
        bot.fail("second")
        _assert_single_complete(bot._transport, status="failed", error="first")

    def test_cancel_reports_cancelled_status(self):
        bot = _owned_bot_with_mock_transport()
        bot.cancel("aborted by user")
        _assert_single_complete(bot._transport, status="cancelled", error="aborted by user")

    def test_close_after_cancel_does_not_override(self):
        bot = _owned_bot_with_mock_transport()
        bot.cancel("aborted by user")
        bot.close()
        # close() must not post a second (success) completion over a cancel.
        _assert_single_complete(bot._transport, status="cancelled", error="aborted by user")

    def test_cancel_after_fail_does_not_override(self):
        bot = _owned_bot_with_mock_transport()
        bot.fail("boom")
        bot.cancel("late ctrl+c")
        # First terminal status wins; cancel is a no-op once failed.
        _assert_single_complete(bot._transport, status="failed", error="boom")

    def test_external_task_is_not_terminalized(self):
        bot = Qirabot(api_key="k", task_id="t")  # external task
        bot._transport = MagicMock()
        bot.fail("boom")
        bot.close()
        assert _complete_calls(bot._transport) == []


class TestQirabotTypeTextParams:
    # type_text() resolves the device adapter before calling _ai_action, so
    # tests that pass a bare string as the target must also mock _get_adapter.
    # (See test_retry.TestRetry.test_click_passes_retry for the same pattern.)

    def _make_mocked_bot(self):
        bot = Qirabot(api_key="k", task_id="t")
        bot._get_adapter = MagicMock(return_value=MagicMock())
        bot._ai_action = MagicMock(return_value={"success": True})
        return bot

    def test_type_text_builds_action_with_press_enter(self):
        bot = self._make_mocked_bot()
        bot.type_text("target", "field", "hello", press_enter=True)
        call_args = bot._ai_action.call_args
        action = call_args.kwargs.get("action") or call_args[1].get("action") or call_args[0][1]
        assert action["params"]["press_enter"] is True
        assert action["params"]["text"] == "hello"
        bot.close()

    def test_type_text_builds_action_with_clear(self):
        bot = self._make_mocked_bot()
        bot.type_text("target", "field", "hello", clear_before_typing=True)
        call_args = bot._ai_action.call_args
        action = call_args.kwargs.get("action") or call_args[1].get("action") or call_args[0][1]
        assert action["params"]["clear_before_typing"] is True
        bot.close()

    def test_type_text_omits_false_flags(self):
        bot = self._make_mocked_bot()
        bot.type_text("target", "field", "hello")
        call_args = bot._ai_action.call_args
        action = call_args.kwargs.get("action") or call_args[1].get("action") or call_args[0][1]
        assert "press_enter" not in action["params"]
        assert "clear_before_typing" not in action["params"]
        bot.close()


class TestQirabotLongPressParams:
    def _make_mocked_bot(self):
        bot = Qirabot(api_key="k", task_id="t")
        bot._get_adapter = MagicMock(return_value=MagicMock())
        bot._ai_action = MagicMock(return_value={"success": True})
        return bot

    def test_long_press_omits_default_duration(self):
        bot = self._make_mocked_bot()
        bot.long_press("target", "app icon")
        call_args = bot._ai_action.call_args
        action = call_args.kwargs.get("action") or call_args[1].get("action") or call_args[0][1]
        assert action["type"] == "long_press"
        assert action["params"] == {"locate": "app icon"}
        bot.close()

    def test_long_press_converts_seconds_to_ms(self):
        bot = self._make_mocked_bot()
        bot.long_press("target", "app icon", duration=1.5)
        call_args = bot._ai_action.call_args
        action = call_args.kwargs.get("action") or call_args[1].get("action") or call_args[0][1]
        assert action["params"]["duration"] == 1500
        bot.close()


class TestPressKey:
    """press_key is a deterministic (no-AI) action: it routes through
    adapter.execute (reusing tab-switch + settle) and returns the current
    target so a tab-opening combo like ctrl+t is followed."""

    def test_executes_action_and_returns_current_target(self):
        bot = Qirabot(api_key="k", task_id="t")
        target, switched = object(), object()  # e.g. ctrl+t opens a new tab
        adapter = MagicMock()
        adapter.current_target = switched
        bot._adapters[id(target)] = adapter

        out = bot.press_key(target, "ctrl+t")

        adapter.execute.assert_called_once_with("press_key", {"key": "ctrl+t"})
        assert out is switched
        bot.close()

    def test_bound_press_key_delegates(self):
        bot = Qirabot(api_key="k", task_id="t")
        target = object()
        adapter = MagicMock()
        adapter.current_target = target
        bot._adapters[id(target)] = adapter

        bot.bind(target).press_key("Enter")

        adapter.execute.assert_called_once_with("press_key", {"key": "Enter"})
        bot.close()


class TestAdapterCacheSync:
    """A tab switch makes current_target a *new* page object. The cache must
    re-register it against the same adapter so passing it back doesn't spawn a
    second, divergent adapter (which previously held a closed tab and crashed)."""

    def test_result_registers_returned_target(self):
        bot = Qirabot(api_key="k", task_id="t")
        p0, v1 = object(), object()  # original page, new-tab page
        adapter = MagicMock()
        adapter.current_target = v1
        bot._adapters[id(p0)] = adapter

        out = bot._result(adapter)

        assert out is v1
        # Passing the returned object back reuses the same adapter (no detect()).
        assert bot._get_adapter(v1) is adapter
        bot.close()

    def test_loop_reuses_single_adapter_across_tab_switches(self):
        bot = Qirabot(api_key="k", task_id="t")
        bot._ai_action = MagicMock(return_value={"success": True})
        p0, v1 = object(), object()
        adapter = MagicMock()
        bot._adapters[id(p0)] = adapter

        adapter.current_target = v1          # click opens a new tab
        out = bot.click(p0, "open")
        assert out is v1

        adapter.current_target = p0          # go_back closes it, back to list
        out2 = bot.go_back(v1)
        assert out2 is p0

        # Both page objects resolve to the one adapter — never a second instance.
        assert bot._get_adapter(p0) is adapter
        assert bot._get_adapter(v1) is adapter
        bot.close()


class TestAdapterCacheEviction:
    """The id()-keyed adapter cache must drop entries when the target dies, so
    a long session doesn't grow it unbounded and a recycled id() can't return a
    stale adapter for an unrelated object."""

    def test_entry_evicted_when_target_garbage_collected(self):
        import gc

        bot = Qirabot(api_key="k", task_id="t")

        class Target:  # plain, weak-referenceable stand-in for a page/driver
            pass

        target = Target()
        bot._cache_adapter(target, MagicMock())
        key = id(target)
        assert key in bot._adapters

        del target
        gc.collect()

        assert key not in bot._adapters
        bot.close()


class TestVerifySsl:
    def test_verify_ssl_forwarded_to_transport(self):
        import qirabot.client as client_mod

        captured = {}

        class FakeTransport:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def close(self):
                pass

        orig = client_mod.Transport
        client_mod.Transport = FakeTransport
        try:
            bot = client_mod.Qirabot(api_key="k", task_id="t", verify_ssl=False)
            bot.close()
        finally:
            client_mod.Transport = orig

        assert captured["verify_ssl"] is False


class TestScreenshotConfig:
    def test_default_is_jpeg(self):
        cfg = ScreenshotConfig()
        assert cfg.format == "jpeg"
        assert cfg.extension == "jpg"
        assert cfg.mime_type == "image/jpeg"

    def test_jpg_normalized_to_jpeg(self):
        cfg = ScreenshotConfig(format="jpg")
        assert cfg.format == "jpeg"
        assert cfg.extension == "jpg"
        assert cfg.mime_type == "image/jpeg"

    def test_png_uppercase_normalized(self):
        cfg = ScreenshotConfig(format="PNG")
        assert cfg.format == "png"
        assert cfg.extension == "png"
        assert cfg.mime_type == "image/png"

    @pytest.mark.parametrize("fmt", ["webp", "gif", "bmp", ""])
    def test_unsupported_format_raises(self, fmt):
        with pytest.raises(ValueError, match="unsupported screenshot_format"):
            ScreenshotConfig(format=fmt)


class TestAnnotateScreenshot:
    """The annotated debug image must be encoded in the configured format so its
    bytes match the filename extension _save_frame derives from the config."""

    def _png_bytes(self, w: int = 200, h: int = 150) -> bytes:
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (w, h), (10, 20, 30)).save(buf, format="PNG")
        return buf.getvalue()

    def test_jpeg_config_produces_jpeg(self):
        import io

        from PIL import Image

        out = _annotate_screenshot(self._png_bytes(), 100, 75, ScreenshotConfig(format="jpeg"))
        assert Image.open(io.BytesIO(out)).format == "JPEG"

    def test_png_config_produces_png(self):
        import io

        from PIL import Image

        out = _annotate_screenshot(self._png_bytes(), 100, 75, ScreenshotConfig(format="png"))
        assert Image.open(io.BytesIO(out)).format == "PNG"

    def test_default_config_produces_jpeg(self):
        import io

        from PIL import Image

        # Default config is jpeg; the annotated bytes must not silently be PNG.
        out = _annotate_screenshot(self._png_bytes(), 100, 75)
        assert Image.open(io.BytesIO(out)).format == "JPEG"
