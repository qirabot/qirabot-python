"""HTTP transport layer for Qirabot SDK."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from qirabot.exceptions import QirabotConnectionError, QirabotTimeoutError, raise_for_error

logger = logging.getLogger("qirabot")


class Transport:
    """HTTP client for Qirabot API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 120.0,
        verify_ssl: bool = True,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_url = f"{self._base_url}/api/v1"
        self._api_key = api_key
        self._headers = {"X-API-Key": api_key}
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=self._api_url,
            headers=self._headers,
            timeout=timeout,
            verify=verify_ssl,
        )

    @contextmanager
    def _mapped_errors(self) -> Iterator[None]:
        """Translate httpx transport errors into friendly Qirabot exceptions.

        Uses ``from None`` so the noisy httpcore/httpx traceback chain is hidden;
        the original message is preserved in the exception text.
        """
        try:
            yield
        except httpx.TimeoutException as e:
            raise QirabotTimeoutError(f"Request to {self._base_url} timed out: {e}") from None
        except httpx.ConnectError as e:
            raise QirabotConnectionError(
                f"Could not connect to {self._base_url}. "
                f"Check that the server is running and QIRA_BASE_URL is correct. ({e})"
            ) from None
        except httpx.RequestError as e:
            raise QirabotConnectionError(f"Network error talking to {self._base_url}: {e}") from None

    def request(self, method: str, path: str, json_data: dict[str, Any] | None = None) -> Any:
        """Send an HTTP request and return parsed JSON response."""
        with self._mapped_errors():
            response = self._client.request(method, path, json=json_data)
        if response.status_code >= 400:
            try:
                data = response.json()
            except Exception:
                data = {"error": {"message": response.text or "Unknown error"}}
            raise_for_error(response.status_code, data)
        if response.status_code == 204:
            return {}
        try:
            return response.json()
        except Exception:
            return {}

    def post(self, path: str, json_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a POST request."""
        result: dict[str, Any] = self.request("POST", path, json_data)
        return result

    def post_multipart(
        self,
        path: str,
        files: dict[str, tuple[str, bytes, str]],
        data: dict[str, str],
    ) -> dict[str, Any]:
        """Send a multipart/form-data POST request."""
        if not files:
            # httpx falls back to urlencoded when files is empty; the server
            # requires multipart. A no-op part forces multipart encoding —
            # the server reads named fields and ignores extras.
            files = {"_": ("", b"", "application/octet-stream")}
        with self._mapped_errors():
            response = self._client.post(path, files=files, data=data)
        if response.status_code >= 400:
            try:
                resp_data = response.json()
            except Exception:
                resp_data = {"error": {"message": response.text or "Unknown error"}}
            raise_for_error(response.status_code, resp_data)
        try:
            result: dict[str, Any] = response.json()
            return result
        except Exception:
            return {}

    def delete(self, path: str) -> dict[str, Any]:
        """Send a DELETE request."""
        result: dict[str, Any] = self.request("DELETE", path)
        return result

    def get_bytes(self, path: str) -> bytes:
        """Send a GET request and return raw bytes."""
        with self._mapped_errors():
            response = self._client.get(path)
        if response.status_code >= 400:
            try:
                data = response.json()
            except Exception:
                data = {"error": {"message": response.text or "Unknown error"}}
            raise_for_error(response.status_code, data)
        return response.content

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()
