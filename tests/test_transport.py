"""Tests for transport layer."""

import httpx
import pytest

from qirabot._transport import Transport
from qirabot.exceptions import QirabotConnectionError, QirabotTimeoutError


class TestTransportInit:
    def test_base_url_trailing_slash_stripped(self):
        t = Transport("https://app.qirabot.com/", "key")
        assert t._base_url == "https://app.qirabot.com"
        assert t._api_url == "https://app.qirabot.com/api/v1"
        t.close()

    def test_api_url_built(self):
        t = Transport("http://localhost:8080", "key")
        assert t._api_url == "http://localhost:8080/api/v1"
        t.close()

    def test_headers_contain_api_key(self):
        t = Transport("http://localhost", "my_key")
        assert t._headers["X-API-Key"] == "my_key"
        t.close()


class TestTransportClose:
    def test_close_does_not_raise(self):
        t = Transport("http://localhost", "key")
        t.close()
        t.close()


def _transport_raising(exc: Exception) -> Transport:
    """A Transport whose underlying client always raises ``exc``."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc
    t = Transport("http://app.example.test", "key")
    t._client = httpx.Client(base_url=t._api_url, transport=httpx.MockTransport(handler))
    return t


class TestTransportErrorMapping:
    def test_connect_error_becomes_connection_error(self):
        t = _transport_raising(httpx.ConnectError("[Errno 8] nodename nor servname provided"))
        with pytest.raises(QirabotConnectionError) as exc_info:
            t.post("/tasks/create", {})
        msg = str(exc_info.value)
        assert "http://app.example.test" in msg
        assert "QIRA_BASE_URL" in msg
        t.close()

    def test_connect_error_hides_original_traceback(self):
        t = _transport_raising(httpx.ConnectError("boom"))
        with pytest.raises(QirabotConnectionError) as exc_info:
            t.post("/tasks/create", {})
        # raised with `from None` -> no chained cause exposed to the user
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__suppress_context__ is True
        t.close()

    def test_timeout_becomes_timeout_error(self):
        t = _transport_raising(httpx.ConnectTimeout("slow"))
        with pytest.raises(QirabotTimeoutError):
            t.post("/tasks/create", {})
        t.close()

    def test_other_request_error_becomes_connection_error(self):
        t = _transport_raising(httpx.ReadError("reset"))
        with pytest.raises(QirabotConnectionError):
            t.get_bytes("/whatever")
        t.close()
