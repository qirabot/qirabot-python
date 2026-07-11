"""Wire-level tests for the built-in WDA client.

Every request WdaClient sends is asserted against the exact URL/JSON shapes
facebook-wda (the reference implementation these were replicated from) is
known to send, using httpx.MockTransport — no real device, but real HTTP
serialization.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from qirabot.exceptions import QirabotError
from qirabot.wda import WdaClient, WdaError

SESSION_ID = "69E6FDBA-8D59-4349-B7DE-A9CA41A97814"


class FakeWda:
    """Programmable WDA server behind httpx.MockTransport, recording requests."""

    def __init__(self):
        self.requests: list[tuple[str, str, dict | None]] = []
        self.session_id: str | None = SESSION_ID
        self.handlers: dict[tuple[str, str], object] = {}
        self.legacy_tap = False  # WDA < 6.0: only /wda/tap/0 exists

    def client(self) -> WdaClient:
        c = WdaClient("http://fake:8100")
        c._http = httpx.Client(
            base_url="http://fake:8100", transport=httpx.MockTransport(self)
        )
        return c

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, body))

        custom = self.handlers.get((request.method, path))
        if custom is not None:
            return custom(request) if callable(custom) else custom

        if (request.method, path) == ("GET", "/status"):
            return httpx.Response(
                200,
                json={
                    "value": {"ready": True, "os": {"version": "17.0"}},
                    "sessionId": self.session_id,
                },
            )
        if (request.method, path) == ("POST", "/session"):
            self.session_id = SESSION_ID
            return httpx.Response(
                200, json={"value": {"sessionId": SESSION_ID}, "sessionId": SESSION_ID}
            )
        if (request.method, path) == ("GET", "/screenshot"):
            return httpx.Response(
                200, json={"value": base64.b64encode(b"\x89PNGfake").decode()}
            )
        if path == f"/session/{SESSION_ID}/window/size":
            return httpx.Response(200, json={"value": {"width": 393, "height": 852}})
        if self.legacy_tap and path == f"/session/{SESSION_ID}/wda/tap":
            return httpx.Response(
                404, json={"value": {"error": "unknown command", "message": "nope"}}
            )
        # Interaction endpoints: generic success.
        return httpx.Response(200, json={"value": None})

    def session_calls(self, suffix: str):
        return [r for r in self.requests if r[1] == f"/session/{SESSION_ID}{suffix}"]


@pytest.fixture
def wda():
    return FakeWda()


class TestWireShapes:
    def test_status_inlines_session_id(self, wda):
        st = wda.client().status()
        assert st["ready"] is True
        assert st["sessionId"] == SESSION_ID

    def test_screenshot_decodes_base64_png(self, wda):
        assert wda.client().screenshot() == b"\x89PNGfake"

    def test_tap_uses_current_session(self, wda):
        wda.client().tap(100, 200)
        assert wda.session_calls("/wda/tap") == [
            ("POST", f"/session/{SESSION_ID}/wda/tap", {"x": 100, "y": 200})
        ]

    def test_tap_falls_back_to_legacy_route_once(self, wda):
        # WDA < 6.0 has /wda/tap/0; the probe result must be remembered.
        wda.legacy_tap = True
        client = wda.client()
        client.tap(1, 2)
        client.tap(3, 4)
        legacy = wda.session_calls("/wda/tap/0")
        assert [b for _, _, b in legacy] == [{"x": 1, "y": 2}, {"x": 3, "y": 4}]
        # the modern route was only probed once
        assert len(wda.session_calls("/wda/tap")) == 1

    def test_double_tap_and_touch_and_hold(self, wda):
        client = wda.client()
        client.double_tap(10, 20)
        client.tap_hold(30, 40, 1.5)
        assert wda.session_calls("/wda/doubleTap")[0][2] == {"x": 10, "y": 20}
        assert wda.session_calls("/wda/touchAndHold")[0][2] == {
            "x": 30, "y": 40, "duration": 1.5,
        }

    def test_swipe_drag_payload(self, wda):
        wda.client().swipe(1, 2, 3, 4, duration=0.5)
        assert wda.session_calls("/wda/dragfromtoforduration")[0][2] == {
            "fromX": 1, "fromY": 2, "toX": 3, "toY": 4, "duration": 0.5,
        }

    def test_send_keys_is_a_char_list(self, wda):
        # facebook-wda sends {"value": list(text)} — a LIST, not a string.
        wda.client().send_keys("hi你")
        assert wda.session_calls("/wda/keys")[0][2] == {"value": ["h", "i", "你"]}

    def test_press_button_and_home_and_lock(self, wda):
        client = wda.client()
        client.press_button("volumeUp")
        client.home()
        client.lock()
        assert wda.session_calls("/wda/pressButton")[0][2] == {"name": "volumeUp"}
        assert ("POST", "/wda/homescreen", None) in wda.requests
        assert ("POST", "/wda/lock", None) in wda.requests

    def test_window_size_rounds_points(self, wda):
        assert wda.client().window_size() == (393, 852)

    def test_app_launch_session_payload(self, wda):
        wda.handlers[("GET", "/wda/locked")] = httpx.Response(200, json={"value": False})
        client = wda.client()
        client.app_launch("com.tencent.xin")
        method, path, body = next(r for r in wda.requests if r[1] == "/session")
        always_match = {
            "bundleId": "com.tencent.xin",
            "arguments": [],
            "environment": {},
            "shouldWaitForQuiescence": False,
        }
        assert body == {
            "capabilities": {"alwaysMatch": always_match},
            "desiredCapabilities": always_match,
        }
        assert client._session_id == SESSION_ID

    def test_app_launch_unlocks_locked_device(self, wda):
        wda.handlers[("GET", "/wda/locked")] = httpx.Response(200, json={"value": True})
        wda.client().app_launch("com.example")
        assert ("POST", "/wda/unlock", None) in wda.requests


class TestSessionLifecycle:
    def test_session_from_status_is_reused(self, wda):
        client = wda.client()
        client.tap(1, 1)
        client.tap(2, 2)
        # session discovered once via /status, never created explicitly
        assert sum(1 for r in wda.requests if r[1] == "/status") == 1
        assert not any(r[1] == "/session" and r[0] == "POST" for r in wda.requests)

    def test_no_current_session_creates_default(self, wda):
        wda.session_id = None
        wda.client().tap(1, 1)
        method, path, body = next(r for r in wda.requests if r[1] == "/session")
        assert body == {"capabilities": {}}

    def test_invalid_session_recreated_once(self, wda):
        client = wda.client()
        client.tap(1, 1)  # caches SESSION_ID
        calls = {"n": 0}

        def flaky(request):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(404, json={"value": {
                    "error": "invalid session id",
                    "message": "Session does not exist",
                }})
            return httpx.Response(200, json={"value": None})

        wda.handlers[("POST", f"/session/{SESSION_ID}/wda/doubleTap")] = flaky
        client.double_tap(5, 6)  # must recover transparently
        assert calls["n"] == 2

    def test_persistent_wda_error_raises(self, wda):
        wda.handlers[("POST", f"/session/{SESSION_ID}/wda/lock")] = httpx.Response(
            500, json={"value": {"error": "unexpected", "message": "boom"}}
        )
        client = wda.client()
        with pytest.raises(WdaError) as ei:
            client._request("POST", "/wda/lock", session=True)
        assert "boom" in str(ei.value)

    def test_unreachable_maps_to_actionable_error(self):
        def refuse(request):
            raise httpx.ConnectError("connection refused")

        client = WdaClient("http://fake:8100")
        client._http = httpx.Client(
            base_url="http://fake:8100", transport=httpx.MockTransport(refuse)
        )
        with pytest.raises(QirabotError) as ei:
            client.status()
        assert ei.value.code == "wda.unreachable"
        assert "iproxy 8100 8100" in str(ei.value)
        assert client.is_ready() is False

    def test_empty_response_raises(self, wda):
        wda.handlers[("POST", "/wda/homescreen")] = httpx.Response(200, text="")
        with pytest.raises(WdaError) as ei:
            wda.client().home()
        assert ei.value.code == "wda.empty_response"
