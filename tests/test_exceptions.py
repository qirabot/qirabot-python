"""Tests for exception classes and raise_for_error."""

import pytest

from qirabot.exceptions import (
    ActionError,
    AuthenticationError,
    InsufficientBalanceError,
    QirabotConnectionError,
    QirabotError,
    QirabotTimeoutError,
    RateLimitError,
    raise_for_error,
)


class TestQirabotError:
    def test_str_with_code(self):
        e = QirabotError("something broke", code="test.error")
        assert str(e) == "[test.error] something broke"

    def test_str_without_code(self):
        e = QirabotError("something broke")
        assert str(e) == "something broke"

    def test_attributes(self):
        e = QirabotError("msg", code="c", status_code=500)
        assert e.message == "msg"
        assert e.code == "c"
        assert e.status_code == 500


class TestRaiseForError:
    def test_auth_by_code(self):
        with pytest.raises(AuthenticationError):
            raise_for_error(401, {"code": "auth.api_key_invalid", "message": "bad key"})

    def test_auth_by_status(self):
        with pytest.raises(AuthenticationError):
            raise_for_error(401, {"message": "unauthorized"})

    def test_insufficient_balance_by_code(self):
        with pytest.raises(InsufficientBalanceError):
            raise_for_error(402, {"code": "finance.insufficient_balance", "message": "no credits"})

    def test_insufficient_balance_by_status(self):
        with pytest.raises(InsufficientBalanceError):
            raise_for_error(402, {"message": "payment required"})

    def test_rate_limit_by_status(self):
        with pytest.raises(RateLimitError):
            raise_for_error(429, {"message": "too many requests"})

    def test_nested_error_format(self):
        with pytest.raises(AuthenticationError, match="invalid key"):
            raise_for_error(401, {"error": {"code": "auth.api_key_missing", "message": "invalid key"}})

    def test_token_missing_code_maps_to_auth(self):
        # The server returns auth.token_missing for an absent key; it must map to
        # AuthenticationError by code, not just fall through to the 401 status.
        with pytest.raises(AuthenticationError):
            raise_for_error(401, {"error": {"code": "auth.token_missing", "message": "Authentication required"}})

    def test_string_error_format(self):
        with pytest.raises(QirabotError, match="something went wrong"):
            raise_for_error(500, {"error": "something went wrong"})

    def test_unknown_code_falls_back_to_status(self):
        with pytest.raises(AuthenticationError):
            raise_for_error(401, {"code": "unknown.code", "message": "unauthorized"})

    def test_unknown_status_falls_back_to_base(self):
        with pytest.raises(QirabotError):
            raise_for_error(500, {"message": "server error"})


class TestExceptionHierarchy:
    @pytest.mark.parametrize("cls", [
        AuthenticationError,
        InsufficientBalanceError,
        RateLimitError,
        ActionError,
        QirabotTimeoutError,
        QirabotConnectionError,
    ])
    def test_subclass_of_qirabot_error(self, cls):
        assert issubclass(cls, QirabotError)

    @pytest.mark.parametrize("cls", [
        AuthenticationError,
        InsufficientBalanceError,
        RateLimitError,
        ActionError,
        QirabotTimeoutError,
        QirabotConnectionError,
    ])
    def test_subclass_of_exception(self, cls):
        assert issubclass(cls, Exception)
