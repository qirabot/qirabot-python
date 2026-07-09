"""Tests for local-step cloud sync (buffer + flush) and section error banners."""

from typing import Any


from qirabot.adapters.base import DeviceAdapter, DeviceInfo
from qirabot.client import _LOCAL_BUF_MAX_BYTES, _LOCAL_BUF_MAX_ENTRIES, Qirabot
from qirabot.exceptions import QirabotError


class _FakeAdapter(DeviceAdapter):
    """Adapter returning real screenshot bytes so local steps get buffered."""

    def __init__(self, shot: bytes = b"img"):
        self._shot = shot

    @classmethod
    def accepts(cls, target):
        return False

    def screenshot(self, config=None):
        return self._shot

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

    def execute(self, action_type, params):
        pass


class _FakeTransport:
    """Records every multipart POST; per-path canned responses / errors."""

    def __init__(self):
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []
        self.responses: dict[str, Any] = {}
        self.errors: dict[str, list[Exception]] = {}

    def post_multipart(self, path, files, data):
        queued = self.errors.get(self._kind(path))
        if queued:
            raise queued.pop(0)
        self.calls.append((path, files, data))
        return self.responses.get(self._kind(path), {})

    @staticmethod
    def _kind(path: str) -> str:
        return "local" if path.endswith("/local-steps") else "act"

    def local_calls(self):
        return [c for c in self.calls if c[0].endswith("/local-steps")]

    def act_calls(self):
        return [c for c in self.calls if c[0].endswith("/act")]

    def post(self, path, json_data=None, timeout=None):
        return {}

    def close(self):
        pass


def _make_bot(tmp_path, **kwargs) -> tuple[Qirabot, _FakeTransport]:
    bot = Qirabot(
        api_key="k",
        task_id="t",
        heartbeat=False,
        report_dir=str(tmp_path),
        **kwargs,
    )
    transport = _FakeTransport()
    bot._transport = transport
    return bot, transport


class TestBufferAndFlush:
    def test_local_action_buffers_without_network(self, tmp_path):
        bot, transport = _make_bot(tmp_path)
        adapter = _FakeAdapter()
        bot._record_local_step(adapter, "press_key", {"key": "Enter"})
        assert len(bot._local_buf) == 1
        entry = bot._local_buf[0]
        assert entry["step_seq"] == 1
        assert entry["action_type"] == "press_key"
        assert entry["params"] == {"key": "Enter"}
        assert entry["screenshot"] == b"img"
        assert entry["ts"].endswith("Z")
        assert transport.calls == []
        bot._closed = True  # skip close-side effects

    def test_flush_before_act_and_no_reflush_on_retry(self, tmp_path):
        bot, transport = _make_bot(tmp_path)
        adapter = _FakeAdapter()
        bot._record_local_step(adapter, "press_key", {"key": "Enter"})

        # Retryable first /act attempt: flush must happen once, before the
        # attempt loop — the retry must not trigger a second flush.
        transport.errors["act"] = [QirabotError("boom", status_code=500)]
        transport.responses["act"] = {"success": True, "finished": False}
        bot._retry_delay = 0.0
        result = bot._post_act_retrying(files={}, data={"request": "{}"})
        assert result == {"success": True, "finished": False}

        assert len(transport.local_calls()) == 1
        assert len(transport.act_calls()) == 1
        # Order: local-steps landed before /act.
        assert transport.calls[0][0].endswith("/local-steps")
        assert bot._local_buf == []
        # Payload shape: request JSON with steps, screenshot part per entry.
        import json

        _, files, data = transport.local_calls()[0]
        body = json.loads(data["request"])
        assert [s["step_seq"] for s in body["steps"]] == [1]
        assert body["steps"][0]["action_type"] == "press_key"
        assert "screenshot_0" in files
        bot._closed = True

    def test_entry_threshold_triggers_flush(self, tmp_path):
        bot, transport = _make_bot(tmp_path)
        adapter = _FakeAdapter()
        for _ in range(_LOCAL_BUF_MAX_ENTRIES):
            bot._record_local_step(adapter, "scroll", {"direction": "down"})
        assert len(transport.local_calls()) == 1
        assert bot._local_buf == []
        bot._closed = True

    def test_byte_threshold_triggers_flush(self, tmp_path):
        bot, transport = _make_bot(tmp_path)
        big = _FakeAdapter(shot=b"x" * (_LOCAL_BUF_MAX_BYTES // 2 + 1))
        bot._record_local_step(big, "press_key", {"key": "a"})
        assert transport.local_calls() == []
        bot._record_local_step(big, "press_key", {"key": "b"})
        assert len(transport.local_calls()) == 1
        assert bot._local_buf_bytes == 0
        bot._closed = True

    def test_close_flushes_remaining_buffer(self, tmp_path):
        bot, transport = _make_bot(tmp_path)
        adapter = _FakeAdapter()
        bot._record_local_step(adapter, "go_back")
        bot.close()
        assert len(transport.local_calls()) == 1

    def test_flush_failure_drops_batch_silently(self, tmp_path):
        bot, transport = _make_bot(tmp_path)
        adapter = _FakeAdapter()
        bot._record_local_step(adapter, "press_key", {"key": "a"})
        transport.errors["local"] = [QirabotError("boom", status_code=500)]
        bot._flush_local_steps()  # must not raise
        assert bot._local_buf == []
        # Next batch still tries (5xx is not the unsupported signal).
        bot._record_local_step(adapter, "press_key", {"key": "b"})
        bot._flush_local_steps()
        assert len(transport.local_calls()) == 1
        bot._closed = True


class TestDowngrade:
    def test_404_downgrades_once(self, tmp_path):
        bot, transport = _make_bot(tmp_path)
        adapter = _FakeAdapter()
        bot._record_local_step(adapter, "press_key", {"key": "a"})
        transport.errors["local"] = [QirabotError("not found", status_code=404)]
        bot._flush_local_steps()
        assert bot._local_sync_supported is False
        # Later local actions are not even buffered, and flushing stays silent.
        bot._record_local_step(adapter, "press_key", {"key": "b"})
        assert bot._local_buf == []
        bot._flush_local_steps()
        assert transport.local_calls() == []
        # The local report still recorded both actions.
        assert len(bot._log) == 2
        bot._closed = True

    def test_terminated_control_stops_sync(self, tmp_path):
        bot, transport = _make_bot(tmp_path)
        adapter = _FakeAdapter()
        transport.responses["local"] = {"control": "terminated"}
        bot._record_local_step(adapter, "press_key", {"key": "a"})
        bot._flush_local_steps()
        assert bot._local_sync_supported is False
        bot._closed = True

    def test_sync_disabled_never_posts(self, tmp_path):
        bot, transport = _make_bot(tmp_path, sync_local_steps=False)
        adapter = _FakeAdapter()
        bot._record_local_step(adapter, "press_key", {"key": "a"})
        assert bot._local_buf == []
        bot._flush_local_steps()
        bot.close()
        assert transport.local_calls() == []
        # Reporting is unaffected.
        assert len(bot._log) == 1

    def test_step_seq_not_consumed_when_disabled(self, tmp_path):
        # With sync off, local actions must not burn step_seq values —
        # /act idempotency seqs stay dense.
        bot, transport = _make_bot(tmp_path, sync_local_steps=False)
        adapter = _FakeAdapter()
        bot._record_local_step(adapter, "press_key", {"key": "a"})
        assert bot._step_seq == 0
        bot._closed = True
