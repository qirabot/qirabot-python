"""Request-level thinking_level override: body construction, fallback
semantics, auto-wait pass-through, bound proxy, and the CLI flag."""

import json
from unittest.mock import MagicMock

from qirabot import Qirabot
from qirabot.adapters.base import DeviceAdapter, DeviceInfo
from qirabot.bound import _BoundQirabot


class _FakeAdapter(DeviceAdapter):
    def __init__(self):
        pass

    @classmethod
    def accepts(cls, target):
        return False

    def screenshot(self, config=None):
        return b"img"

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


def _extract_request(call_kwargs):
    return json.loads(call_kwargs["data"]["request"])


class TestSingleActionBody:
    """The four quadrants of the per-call vs instance-default fallback on the
    _ai_action_once request body."""

    def _bot(self, **kwargs):
        bot = Qirabot(api_key="k", task_id="t", **kwargs)
        bot._get_adapter = lambda target: _FakeAdapter()
        bot._record_step = lambda *a, **k: None
        bot._transport.post_multipart = MagicMock(return_value={
            "success": True, "finished": True, "actionType": "extract",
            "output": "42",
        })
        return bot

    def _sent_body(self, bot):
        return _extract_request(bot._transport.post_multipart.call_args.kwargs)

    def test_both_empty_omits_field(self):
        bot = self._bot()
        bot.extract("target", "read it")
        assert "thinking_level" not in self._sent_body(bot)
        bot.close()

    def test_instance_default_applies(self):
        bot = self._bot(thinking_level="low")
        bot.extract("target", "read it")
        assert self._sent_body(bot)["thinking_level"] == "low"
        bot.close()

    def test_per_call_applies(self):
        bot = self._bot()
        bot.extract("target", "read it", thinking_level="high")
        assert self._sent_body(bot)["thinking_level"] == "high"
        bot.close()

    def test_per_call_overrides_instance(self):
        bot = self._bot(thinking_level="low")
        bot.extract("target", "read it", thinking_level="high")
        assert self._sent_body(bot)["thinking_level"] == "high"
        bot.close()


class TestAiLoopBody:
    def _bot(self, **kwargs):
        bot = Qirabot(api_key="k", task_id="t", **kwargs)
        bot._get_adapter = lambda target: _FakeAdapter()
        bot._record_step = lambda *a, **k: None
        bot._sent = []

        def post(**kw):
            bot._sent.append(_extract_request(kw))
            return {
                "success": True, "finished": True, "actionType": "done",
                "params": {"result": "ok", "success": True}, "output": "ok",
            }

        bot._post_act_retrying = post
        return bot

    def test_per_call_in_every_loop_request(self):
        bot = self._bot()
        bot.ai(object(), "task", max_steps=2, thinking_level="medium")
        assert bot._sent and all(b["thinking_level"] == "medium" for b in bot._sent)
        bot.close()

    def test_instance_default_in_loop(self):
        bot = self._bot(thinking_level="minimal")
        bot.ai(object(), "task", max_steps=2)
        assert bot._sent and all(b["thinking_level"] == "minimal" for b in bot._sent)
        bot.close()

    def test_absent_when_unset(self):
        bot = self._bot()
        bot.ai(object(), "task", max_steps=2)
        assert bot._sent and all("thinking_level" not in b for b in bot._sent)
        bot.close()


class TestAutoWaitChain:
    """The auto-wait verify of click(timeout>0) must run at the same thinking
    level as the click itself — both LLM calls belong to one user action."""

    def _bot(self):
        bot = Qirabot(api_key="k", task_id="t")
        bot._get_adapter = lambda target: _FakeAdapter()
        bot._record_step = lambda *a, **k: None
        bot._ai_action = MagicMock(return_value={
            "success": True, "finished": True,
            "actionType": "click", "params": {"x": 1, "y": 2},
        })
        return bot

    def test_click_auto_wait_carries_thinking_level(self):
        bot = self._bot()
        bot.wait_for = MagicMock()
        bot.click("target", "OK", timeout=5, thinking_level="high")
        assert bot.wait_for.call_args.kwargs["thinking_level"] == "high"
        assert bot._ai_action.call_args.kwargs["thinking_level"] == "high"
        bot.close()

    def test_wait_for_passes_to_verify(self):
        bot = self._bot()
        bot.verify = MagicMock()  # truthy -> met on first poll
        bot.wait_for("target", "cart shows 1 item", timeout=1, thinking_level="medium")
        assert bot.verify.call_args.kwargs["thinking_level"] == "medium"
        bot.close()


class TestBoundProxy:
    def test_action_methods_pass_through(self):
        inner = MagicMock()
        bound = _BoundQirabot(inner, target="tgt")
        bound.click("OK", thinking_level="high")
        assert inner.click.call_args.kwargs["thinking_level"] == "high"
        bound.extract("read it", thinking_level="low")
        assert inner.extract.call_args.kwargs["thinking_level"] == "low"
        bound.ai("do it", thinking_level="medium")
        assert inner.ai.call_args.kwargs["thinking_level"] == "medium"
        bound.wait_for("done", thinking_level="minimal")
        assert inner.wait_for.call_args.kwargs["thinking_level"] == "minimal"


class TestCliFlag:
    def test_thinking_level_reaches_make_bot(self, monkeypatch):
        from click.testing import CliRunner

        from qirabot.cli import main

        captured = {}

        def spy_make_bot(ctx, **kwargs):
            captured.update(kwargs)
            return MagicMock(name="bot")

        monkeypatch.setattr(main, "_make_bot", spy_make_bot)
        monkeypatch.setattr(main, "_run_local", lambda *a, **k: None)

        result = CliRunner().invoke(main.cli, ["browser", "do it", "--thinking-level", "high"])
        assert result.exit_code == 0, result.output
        assert captured["thinking_level"] == "high"

    def test_default_is_empty(self, monkeypatch):
        from click.testing import CliRunner

        from qirabot.cli import main

        captured = {}

        def spy_make_bot(ctx, **kwargs):
            captured.update(kwargs)
            return MagicMock(name="bot")

        monkeypatch.setattr(main, "_make_bot", spy_make_bot)
        monkeypatch.setattr(main, "_run_local", lambda *a, **k: None)

        result = CliRunner().invoke(main.cli, ["browser", "do it"])
        assert result.exit_code == 0, result.output
        assert captured["thinking_level"] == ""
