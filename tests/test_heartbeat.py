"""Heartbeat thread + /act control-response handling.

The heartbeat proves the client process is alive so scripts can sleep
between bot.ai calls without the server's orphan cleaner reclaiming the
task; the control branch is how a script finally learns its task was
terminated server-side.
"""

import threading
import time

import pytest

from qirabot import Qirabot
from qirabot._heartbeat import HEARTBEAT_TIMEOUT, Heartbeat
from qirabot.exceptions import (
    ActionError,
    QirabotConnectionError,
    QirabotError,
    TaskTerminatedError,
    _is_retryable,
)

from .test_client import _SettleFakeAdapter

INTERVAL = 0.005


class _FakeTransport:
    """Scriptable transport: each heartbeat pops the next canned response.

    Responses are dicts (returned) or exceptions (raised); the last one
    repeats forever. `beats` counts heartbeat posts; `done` fires once at
    least `expect` beats have happened, so tests wait on real signals
    instead of sleeping fixed amounts.
    """

    def __init__(self, responses, expect=1):
        self.responses = list(responses)
        self.calls = []
        self.beats = 0
        self.done = threading.Event()
        self._expect = expect

    def post(self, path, json_data=None, timeout=None):
        self.calls.append((path, timeout))
        self.beats += 1
        result = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if self.beats >= self._expect:
            self.done.set()
        if isinstance(result, Exception):
            raise result
        return result

    def post_multipart(self, *a, **kw):  # pragma: no cover - heartbeat never uploads
        raise AssertionError("unexpected multipart post")

    def close(self):
        pass


def _run(transport, on_terminated=None):
    hb = Heartbeat(transport, "task-12345678", on_terminated=on_terminated, interval=INTERVAL)
    hb.start()
    return hb


def _wait_dead(hb):
    hb.join(timeout=2.0)
    assert not hb.is_alive()


class TestHeartbeatThread:
    def test_beats_until_stopped_with_short_timeout(self):
        transport = _FakeTransport([{"status": "running"}], expect=3)
        hb = _run(transport)
        assert transport.done.wait(timeout=2.0)
        hb.stop()
        assert not hb.is_alive()
        # Every beat hits the heartbeat path with the dedicated short timeout.
        for path, timeout in transport.calls:
            assert path == "/tasks/task-12345678/heartbeat"
            assert timeout == HEARTBEAT_TIMEOUT

    def test_pending_status_keeps_beating(self):
        # 'pending' (before the first /act) is non-terminal: keep going.
        transport = _FakeTransport([{"status": "pending"}], expect=3)
        hb = _run(transport)
        assert transport.done.wait(timeout=2.0)
        assert hb.is_alive()
        hb.stop()

    def test_terminal_status_stops_and_flags(self):
        seen = []
        transport = _FakeTransport([{"status": "timeout"}])
        hb = _run(transport, on_terminated=seen.append)
        _wait_dead(hb)
        assert seen == ["timeout"]
        assert transport.beats == 1

    def test_route_404_disables_without_flagging(self):
        # Old server: gin's route-level 404 carries no structured code. The
        # thread must go quiet for the session and must NOT mark the task
        # terminated — it is alive and well on the old rules.
        seen = []
        transport = _FakeTransport([QirabotError("404 page not found", code=None, status_code=404)])
        hb = _run(transport, on_terminated=seen.append)
        _wait_dead(hb)
        assert seen == []
        assert transport.beats == 1

    def test_task_not_found_stops_and_flags(self):
        seen = []
        transport = _FakeTransport(
            [QirabotError("Task not found", code="task.not_found", status_code=404)]
        )
        hb = _run(transport, on_terminated=seen.append)
        _wait_dead(hb)
        assert seen == [""]

    def test_network_error_retries_next_round(self):
        # A blip must not kill the thread: error, error, then healthy again.
        transport = _FakeTransport(
            [
                QirabotConnectionError("net down"),
                QirabotConnectionError("still down"),
                {"status": "running"},
            ],
            expect=4,
        )
        hb = _run(transport)
        assert transport.done.wait(timeout=2.0)
        assert hb.is_alive()
        hb.stop()


class TestClientWiring:
    def test_heartbeat_param_disables(self):
        bot = Qirabot(api_key="k", task_id="t", heartbeat=False)
        assert bot._heartbeat is None
        bot.close()

    def test_env_kill_switch(self, monkeypatch):
        monkeypatch.setenv("QIRA_HEARTBEAT", "0")
        bot = Qirabot(api_key="k", task_id="t")
        assert bot._heartbeat is None
        bot.close()

    def test_default_starts_and_close_stops(self):
        bot = Qirabot(api_key="k", task_id="t")
        assert bot._heartbeat is not None
        assert bot._heartbeat.is_alive()
        bot.close()
        # stop() joins with a grace; the thread idles in Event.wait so it
        # exits promptly.
        deadline = time.monotonic() + 2.0
        while bot._heartbeat.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not bot._heartbeat.is_alive()

    def test_external_task_still_beats(self):
        # The SDK is the executor even for externally-created tasks, so
        # liveness is its to prove.
        bot = Qirabot(api_key="k", task_id="external-task")
        assert bot._heartbeat is not None
        bot.close()

    def test_server_terminated_flag_suppresses_complete(self):
        from .test_close_status import _FakeTransport as _CompleteCapture

        bot = Qirabot(api_key="k", task_id="t", heartbeat=False)
        bot._external_task = False
        transport = _CompleteCapture()
        bot._transport = transport
        bot._on_server_terminated("timeout")
        bot.close()
        assert transport.completions() == []


TERMINATED = {
    "success": False,
    "finished": True,
    "control": "terminated",
    "status": "timeout",
    "error": "task already timeout: task heartbeat lost",
}


def _bot_for_act(act_result):
    bot = Qirabot(api_key="k", task_id="t", heartbeat=False)
    bot._external_task = False
    from .test_close_status import _FakeTransport as _CompleteCapture

    transport = _CompleteCapture()
    bot._transport = transport
    bot._get_adapter = lambda target: _SettleFakeAdapter()
    bot._record_step = lambda *a, **k: None
    bot._execute_action = lambda *a, **k: None
    bot._post_act_retrying = lambda **kw: act_result
    return bot, transport


class TestControlResponse:
    def test_ai_loop_raises_task_terminated(self):
        bot, transport = _bot_for_act(TERMINATED)
        with pytest.raises(TaskTerminatedError) as exc:
            bot.ai(object(), "keep going", max_steps=3)
        assert exc.value.task_status == "timeout"
        assert "task heartbeat lost" in str(exc.value)
        # The server already holds the terminal state; close() must not
        # report /complete on top of it.
        assert bot._terminalized is True
        bot.close()
        assert transport.completions() == []

    def test_direct_path_raises_task_terminated(self):
        bot, transport = _bot_for_act(TERMINATED)
        bot._transport.post_multipart = lambda *a, **kw: TERMINATED
        with pytest.raises(TaskTerminatedError):
            bot._ai_action(object(), {"type": "assert", "params": {}}, execute_result=False)
        assert bot._terminalized is True
        bot.close()

    def test_unknown_control_falls_through_to_plain_failure(self):
        # A future control value (e.g. "paused") must NOT be misreported as
        # terminated by this SDK — it takes the ordinary failure path with
        # the server's message intact.
        bot, _ = _bot_for_act(
            {
                "success": False,
                "finished": False,
                "control": "paused",
                "error": "task paused: operator hold",
            }
        )
        with pytest.raises(ActionError, match="task paused"):
            bot.ai(object(), "keep going", max_steps=3)
        assert bot._terminalized is False
        bot.close()

    def test_task_terminated_error_is_not_retryable(self):
        assert not _is_retryable(TaskTerminatedError("task already timeout"))
