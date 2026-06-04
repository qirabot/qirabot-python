"""Tests for transport layer."""

import pytest
from unittest.mock import MagicMock, patch

from qirabot._transport import Transport


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
