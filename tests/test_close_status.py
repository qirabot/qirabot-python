"""close()'s auto-complete status follows the last ai() outcome.

A run whose final command errored must be recorded failed, not completed —
including when close() runs via atexit after the script crashed out of ai()
without calling fail().
"""

import pytest

from qirabot import Qirabot
from qirabot.exceptions import ActionError

from .test_client import _SettleFakeAdapter


class _FakeTransport:
    """Captures /complete calls; swallows everything else."""

    def __init__(self):
        self.posts = []

    def post(self, path, json_data=None, **kw):
        self.posts.append((path, json_data))
        return {}

    def post_multipart(self, *a, **kw):  # pragma: no cover - not used here
        raise AssertionError("unexpected multipart post")

    def close(self):
        pass

    def completions(self):
        return [p for p in self.posts if p[0].endswith("/complete")]


def _bot_with_transport(act_result):
    bot = Qirabot(api_key="k", task_id="t")
    # Own the task so close() auto-completes it (task_id= normally means an
    # externally owned task, which close() must not touch).
    bot._external_task = False
    transport = _FakeTransport()
    bot._transport = transport
    bot._get_adapter = lambda target: _SettleFakeAdapter()
    bot._record_step = lambda *a, **k: None
    bot._execute_action = lambda *a, **k: None
    if isinstance(act_result, Exception):
        def post_act(**kw):
            raise act_result
        bot._post_act_retrying = post_act
    else:
        bot._post_act_retrying = lambda **kw: act_result
    return bot, transport


DONE = {
    "success": True, "finished": True, "actionType": "done",
    "params": {"result": "done", "success": True}, "output": "done",
}


class TestCloseStatusFollowsLastAiOutcome:
    def test_ai_exception_then_close_marks_failed(self):
        # Mirrors a script crashing out of ai() (e.g. 400 invalid
        # exclude_tools) with close() left to atexit.
        bot, transport = _bot_with_transport(ActionError("invalid exclude_tools: unknown tool"))
        with pytest.raises(ActionError):
            bot.ai(object(), "do thing", max_steps=3)
        bot.close()

        completions = transport.completions()
        assert len(completions) == 1
        _, body = completions[0]
        assert body == {
            "status": "failed",
            "errorMessage": "invalid exclude_tools: unknown tool",
        }

    def test_server_terminal_error_marks_failed(self):
        # Non-raising error ending (finished error body) counts too.
        bot, transport = _bot_with_transport({
            "success": False, "finished": True, "error": "session expired",
        })
        result = bot.ai(object(), "do thing", max_steps=3)
        assert result.status == "error"
        bot.close()

        _, body = transport.completions()[0]
        assert body["status"] == "failed"
        assert body["errorMessage"] == "session expired"

    def test_clean_run_completes(self):
        bot, transport = _bot_with_transport(DONE)
        bot.ai(object(), "do thing", max_steps=3)
        bot.close()

        _, body = transport.completions()[0]
        assert body is None, "clean runs keep the default completed status"

    def test_recovered_error_completes(self):
        # An earlier errored ai() followed by a successful one: the run
        # recovered, so auto-complete stays completed.
        bot, transport = _bot_with_transport(ActionError("boom"))
        with pytest.raises(ActionError):
            bot.ai(object(), "first", max_steps=3)
        bot._post_act_retrying = lambda **kw: DONE
        bot.ai(object(), "second", max_steps=3)
        bot.close()

        _, body = transport.completions()[0]
        assert body is None

    def test_goal_failed_still_completes(self):
        # goal_failed means the command ran cleanly but the goal was
        # unreachable; whether that fails the task is the script's call.
        bot, transport = _bot_with_transport({
            "success": True, "finished": True, "actionType": "done",
            "params": {"result": "login wall", "success": False},
            "output": "login wall",
        })
        result = bot.ai(object(), "do thing", max_steps=3)
        assert result.status == "goal_failed"
        bot.close()

        _, body = transport.completions()[0]
        assert body is None

    def test_explicit_fail_wins_over_auto_status(self):
        bot, transport = _bot_with_transport(ActionError("boom"))
        with pytest.raises(ActionError):
            bot.ai(object(), "do thing", max_steps=3)
        bot.fail("my own message")
        bot.close()

        completions = transport.completions()
        assert len(completions) == 1, "close() must not double-report after fail()"
        assert completions[0][1]["errorMessage"] == "my own message"

    def test_external_task_untouched(self):
        bot, transport = _bot_with_transport(ActionError("boom"))
        bot._external_task = True
        with pytest.raises(ActionError):
            bot.ai(object(), "do thing", max_steps=3)
        bot.close()

        assert transport.completions() == []
