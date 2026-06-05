"""Tests for retry logic in Qirabot client."""

from unittest.mock import MagicMock

import pytest

from qirabot.client import Qirabot
from qirabot.exceptions import (
    AuthenticationError,
    InsufficientBalanceError,
    QirabotError,
    QirabotTimeoutError,
    _is_retryable,
)


class TestIsRetryable:
    def test_timeout_is_retryable(self):
        assert _is_retryable(QirabotTimeoutError("timeout")) is True

    def test_server_error_is_retryable(self):
        assert _is_retryable(QirabotError("fail", status_code=500)) is True

    def test_502_is_retryable(self):
        assert _is_retryable(QirabotError("bad gateway", status_code=502)) is True

    def test_429_is_retryable(self):
        assert _is_retryable(QirabotError("rate limit", status_code=429)) is True

    def test_408_is_retryable(self):
        assert _is_retryable(QirabotError("request timeout", status_code=408)) is True

    def test_auth_error_not_retryable(self):
        assert _is_retryable(AuthenticationError("bad key", status_code=401)) is False

    def test_balance_error_not_retryable(self):
        assert _is_retryable(InsufficientBalanceError("no credits", status_code=402)) is False

    def test_400_not_retryable(self):
        assert _is_retryable(QirabotError("bad request", status_code=400)) is False

    def test_no_status_code_is_retryable(self):
        assert _is_retryable(QirabotError("generic error")) is True


class TestRetry:
    def _make_bot(self, retry=2, retry_delay=0.01):
        bot = Qirabot(api_key="k", task_id="test-task", retry=retry, retry_delay=retry_delay)
        return bot

    def test_retry_on_transient_error(self):
        bot = self._make_bot()
        call_count = 0

        def fake_action_once(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise QirabotError("server error", status_code=500)
            return {"success": True, "actionType": "click", "params": {"x": 1, "y": 2}}

        bot._ai_action_once = MagicMock(side_effect=fake_action_once)
        result = bot._ai_action("target", {"type": "click", "params": {"locate": "btn"}})
        assert result["success"] is True
        assert call_count == 3
        bot.close()

    def test_no_retry_on_auth_error(self):
        bot = self._make_bot()
        bot._ai_action_once = MagicMock(
            side_effect=AuthenticationError("bad key", status_code=401)
        )
        with pytest.raises(AuthenticationError):
            bot._ai_action("target", {"type": "click", "params": {"locate": "btn"}})
        assert bot._ai_action_once.call_count == 1
        bot.close()

    def test_no_retry_on_balance_error(self):
        bot = self._make_bot()
        bot._ai_action_once = MagicMock(
            side_effect=InsufficientBalanceError("no credits", status_code=402)
        )
        with pytest.raises(InsufficientBalanceError):
            bot._ai_action("target", {"type": "click", "params": {"locate": "btn"}})
        assert bot._ai_action_once.call_count == 1
        bot.close()

    def test_raises_after_max_retries(self):
        bot = self._make_bot(retry=2)
        bot._ai_action_once = MagicMock(
            side_effect=QirabotTimeoutError("timeout")
        )
        with pytest.raises(QirabotTimeoutError):
            bot._ai_action("target", {"type": "click", "params": {"locate": "btn"}})
        assert bot._ai_action_once.call_count == 3  # 1 + 2 retries
        bot.close()

    def test_per_call_retry_override(self):
        bot = self._make_bot(retry=0)  # global: no retry
        bot._ai_action_once = MagicMock(
            side_effect=QirabotError("fail", status_code=500)
        )
        with pytest.raises(QirabotError):
            bot._ai_action("target", {"type": "click", "params": {}}, retry=1)
        assert bot._ai_action_once.call_count == 2  # 1 + 1 retry
        bot.close()

    def test_retry_zero_means_no_retry(self):
        bot = self._make_bot(retry=0)
        bot._ai_action_once = MagicMock(
            side_effect=QirabotError("fail", status_code=500)
        )
        with pytest.raises(QirabotError):
            bot._ai_action("target", {"type": "click", "params": {}})
        assert bot._ai_action_once.call_count == 1
        bot.close()

    def test_click_passes_retry(self):
        bot = self._make_bot()
        mock_adapter = MagicMock()
        bot._get_adapter = MagicMock(return_value=mock_adapter)
        bot._ai_action = MagicMock(return_value={"success": True})
        bot.click("target", "button", retry=3)
        call_kwargs = bot._ai_action.call_args.kwargs
        assert call_kwargs["retry"] == 3
        bot.close()

    def test_init_stores_retry_params(self):
        bot = Qirabot(api_key="k", task_id="t", retry=5, retry_delay=2.0)
        assert bot._retry == 5
        assert bot._retry_delay == 2.0
        bot.close()


class TestStepSeqIdempotency:
    """Verify the client sends a stable step_seq across retries so the server
    can de-dup. Without this, a 5xx + retry would double-charge the user."""

    def _make_bot(self, retry=2, retry_delay=0.01):
        return Qirabot(api_key="k", task_id="test-task", retry=retry, retry_delay=retry_delay)

    def test_step_seq_starts_at_zero(self):
        bot = self._make_bot()
        assert bot._step_seq == 0
        bot.close()

    def test_step_seq_increments_per_logical_step(self):
        """Two independent _ai_action calls get two different step_seq values."""
        bot = self._make_bot()
        seen_seqs = []

        def capture(*args, **kwargs):
            seen_seqs.append(kwargs.get("step_seq"))
            return {"success": True, "actionType": "click", "params": {}}

        bot._ai_action_once = MagicMock(side_effect=capture)
        bot._ai_action("target", {"type": "click", "params": {"locate": "a"}})
        bot._ai_action("target", {"type": "click", "params": {"locate": "b"}})
        assert seen_seqs == [1, 2]
        bot.close()

    def test_retry_reuses_step_seq(self):
        """A retried _ai_action must hit _ai_action_once with the SAME step_seq
        every attempt — otherwise the server's idempotency cache can't match."""
        bot = self._make_bot(retry=2)
        seen_seqs = []
        call_count = 0

        def fake(*args, **kwargs):
            nonlocal call_count
            seen_seqs.append(kwargs.get("step_seq"))
            call_count += 1
            if call_count < 3:
                raise QirabotError("transient", status_code=500)
            return {"success": True, "actionType": "click", "params": {}}

        bot._ai_action_once = MagicMock(side_effect=fake)
        bot._ai_action("target", {"type": "click", "params": {"locate": "x"}})
        assert call_count == 3
        assert seen_seqs == [1, 1, 1]
        # The counter advanced once for the whole step, not three times.
        assert bot._step_seq == 1
        bot.close()

    def test_step_seq_independent_across_retried_steps(self):
        """First step retries then succeeds; second step starts fresh at seq=2."""
        bot = self._make_bot(retry=1)
        seen_seqs = []
        call_count = 0

        def fake(*args, **kwargs):
            nonlocal call_count
            seen_seqs.append(kwargs.get("step_seq"))
            call_count += 1
            # First step fails once, succeeds on retry. Second step succeeds first try.
            if call_count == 1:
                raise QirabotError("transient", status_code=500)
            return {"success": True, "actionType": "click", "params": {}}

        bot._ai_action_once = MagicMock(side_effect=fake)
        bot._ai_action("target", {"type": "click", "params": {"locate": "a"}})
        bot._ai_action("target", {"type": "click", "params": {"locate": "b"}})
        assert seen_seqs == [1, 1, 2]
        bot.close()


class TestAiLoopRetry:
    """The multi-step ai() loop must be as resilient to transient errors as the
    single-action path, retrying each /act post while holding step_seq constant
    so the server's idempotency cache replays instead of re-charging."""

    def _make_bot(self, retry=2, retry_delay=0.01):
        return Qirabot(api_key="k", task_id="t", retry=retry, retry_delay=retry_delay)

    def _fake_adapter(self):
        adapter = MagicMock()
        adapter.screenshot.return_value = b"img"
        adapter.device_info.return_value.to_dict.return_value = {
            "platform": "web", "width": 10, "height": 10,
        }
        return adapter

    def test_loop_retries_transient_then_succeeds(self):
        bot = self._make_bot(retry=2)
        bot._get_adapter = MagicMock(return_value=self._fake_adapter())
        calls = []

        def fake_post(path=None, files=None, data=None, **kw):
            calls.append(data)
            if len(calls) < 3:
                raise QirabotError("server error", status_code=500)
            return {"success": True, "finished": True, "output": "done", "actionType": "done"}

        bot._transport.post_multipart = MagicMock(side_effect=fake_post)
        result = bot.ai("target", "do it", max_steps=5)

        assert result.success is True
        # 2 transient failures + 1 success, all within a single step...
        assert len(calls) == 3
        # ...so every attempt carried the SAME body (same step_seq).
        assert calls[0] == calls[1] == calls[2]
        bot.close()

    def test_loop_does_not_retry_non_retryable(self):
        bot = self._make_bot(retry=3)
        bot._get_adapter = MagicMock(return_value=self._fake_adapter())
        calls = []

        def fake_post(path=None, files=None, data=None, **kw):
            calls.append(1)
            raise AuthenticationError("bad key", status_code=401)

        bot._transport.post_multipart = MagicMock(side_effect=fake_post)
        with pytest.raises(AuthenticationError):
            bot.ai("target", "do it")
        assert len(calls) == 1  # no retries on an auth error
        bot.close()
