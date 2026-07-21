"""Tests for the on-screen progress overlay (qirabot.overlay).

The GUI itself can't run headless; these tests cover the parent side — the
process plumbing, the wire protocol, the no-op degradation guarantees — with
a fake Popen, plus the helper's unsupported-platform exit code for real.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from qirabot.client import StepResult
from qirabot.overlay import Overlay, _format_step


class _FakeStdin:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.data = b""
        self.closed = False

    def write(self, b: bytes) -> int:
        if self.fail:
            raise BrokenPipeError("helper died")
        self.data += b
        return len(b)

    def flush(self) -> None:
        if self.fail:
            raise BrokenPipeError("helper died")

    def close(self) -> None:
        self.closed = True


class _FakeProc:
    def __init__(self, fail: bool = False):
        self.stdin = _FakeStdin(fail=fail)
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        self.killed = True


@pytest.fixture
def fake_spawn(monkeypatch):
    """Force a supported platform and capture the helper spawn."""
    monkeypatch.setattr(sys, "platform", "darwin")
    procs: list[_FakeProc] = []

    def popen(cmd, **kwargs):
        assert cmd[1:] == ["-m", "qirabot._overlay_helper"]
        proc = _FakeProc()
        procs.append(proc)
        return proc

    monkeypatch.setattr("qirabot.overlay.subprocess.Popen", popen)
    return procs


def _sent_lines(proc: _FakeProc) -> list[dict]:
    return [json.loads(line) for line in proc.stdin.data.decode().splitlines()]


def _step(**kwargs) -> StepResult:
    defaults = dict(step=3, action_type="click")
    defaults.update(kwargs)
    return StepResult(**defaults)


def test_set_text_sends_one_json_line(fake_spawn):
    ov = Overlay()
    ov.set_text("hello 你好")
    assert _sent_lines(fake_spawn[0]) == [{"text": "hello 你好"}]
    # The wire must stay pure ASCII (\uXXXX escapes): the helper's stdin
    # decoding follows the OS locale (GBK on Chinese Windows), and raw UTF-8
    # on the pipe came out as mojibake there.
    assert fake_spawn[0].stdin.data.isascii()


def test_start_is_lazy_and_idempotent(fake_spawn):
    ov = Overlay()
    assert fake_spawn == []
    ov.set_text("a")
    ov.set_text("b")
    ov.start()
    assert len(fake_spawn) == 1


def test_step_renders_action_and_decision(fake_spawn):
    ov = Overlay()
    ov.step(_step(params={"locate": "Login button"}, decision="need to sign in"))
    (msg,) = _sent_lines(fake_spawn[0])
    assert msg["text"] == 'step 3 · click · "Login button"\nneed to sign in'


def test_close_sends_command_and_closes_stdin(fake_spawn):
    ov = Overlay()
    ov.set_text("x")
    ov.close()
    proc = fake_spawn[0]
    assert _sent_lines(proc)[-1] == {"cmd": "close", "linger": 0.0}
    assert proc.stdin.closed
    # Close is idempotent and post-close sends must not respawn silently
    # against a dead handle.
    ov.close()


def test_unsupported_platform_is_noop(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    spawned = []
    monkeypatch.setattr(
        "qirabot.overlay.subprocess.Popen",
        lambda *a, **k: spawned.append(a),
    )
    ov = Overlay()
    ov.start()
    ov.set_text("ignored")
    ov.step(_step())
    ov.close()
    assert spawned == []


def test_helper_death_degrades_to_noop(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    procs: list[_FakeProc] = []

    def popen(cmd, **kwargs):
        proc = _FakeProc(fail=True)
        procs.append(proc)
        return proc

    monkeypatch.setattr("qirabot.overlay.subprocess.Popen", popen)
    ov = Overlay()
    ov.set_text("first write fails")
    ov.set_text("and must not respawn")
    ov.close()
    assert len(procs) == 1
    # The pipe must be closed on failure, or the buffered writer would
    # re-flush at interpreter shutdown and print an "Exception ignored"
    # BrokenPipeError traceback.
    assert procs[0].stdin.closed


def test_spawn_failure_degrades_to_noop(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = []

    def popen(cmd, **kwargs):
        calls.append(cmd)
        raise OSError("no python")

    monkeypatch.setattr("qirabot.overlay.subprocess.Popen", popen)
    ov = Overlay()
    ov.set_text("a")
    ov.set_text("b")
    assert len(calls) == 1  # failed once, then stopped trying


def test_finish_shows_outcome(fake_spawn):
    ov = Overlay()
    ov.finish(True, "Note created")
    ov.finish(False, "")
    lines = _sent_lines(fake_spawn[0])
    assert lines[0] == {"text": "✓ Note created"}
    assert lines[1] == {"text": "✗"}


def test_close_forwards_linger(fake_spawn):
    ov = Overlay()
    ov.set_text("x")
    ov.close(linger=1.5)
    assert _sent_lines(fake_spawn[0])[-1] == {"cmd": "close", "linger": 1.5}


def test_wrap_chains_user_callback(fake_spawn):
    ov = Overlay()
    seen = []
    chained = ov.wrap(seen.append)
    step = _step()
    chained(step)
    assert seen == [step]
    assert _sent_lines(fake_spawn[0])  # overlay was fed too


def test_wrap_without_user_callback_is_step(fake_spawn):
    ov = Overlay()
    assert ov.wrap(None) == ov.step


def test_context_manager_spawns_and_closes(fake_spawn):
    with Overlay() as ov:
        ov.set_text("running")
    proc = fake_spawn[0]
    assert _sent_lines(proc)[-1] == {"cmd": "close", "linger": 0.0}


def test_format_step_clips_long_text():
    text = _format_step(
        _step(params={"locate": "x" * 200}, decision="d" * 200)
    )
    head, decision = text.split("\n")
    assert len(head) <= 60 and head.endswith("…")
    # The decision gets two wrapped lines' worth of budget.
    assert len(decision) <= 120 and decision.endswith("…")


def test_format_step_type_text_and_scroll():
    assert (
        _format_step(_step(action_type="type", params={"text": "hi"}))
        == 'step 3 · type · ← "hi"'
    )
    assert (
        _format_step(
            _step(action_type="scroll", params={"direction": "down", "amount": 300})
        )
        == "step 3 · scroll · down 300"
    )


@pytest.mark.skipif(
    sys.platform in ("darwin", "win32"),
    reason="on GUI platforms the helper would open a real window",
)
def test_helper_exits_3_on_unsupported_platform():
    proc = subprocess.run(
        [sys.executable, "-m", "qirabot._overlay_helper"],
        input=b"",
        capture_output=True,
        timeout=30,
    )
    assert proc.returncode == 3
