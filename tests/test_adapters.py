"""Tests for adapter base execute() dispatch logic."""

from unittest.mock import MagicMock

import pytest

from qirabot.adapters.base import DeviceAdapter, DeviceInfo


class FakeAdapter(DeviceAdapter):
    """Minimal concrete adapter for testing execute() dispatch."""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    @classmethod
    def accepts(cls, target):
        return False

    def screenshot(self, config=None):
        return b""

    def click(self, x, y):
        self.calls.append(("click", (x, y)))

    def double_click(self, x, y):
        self.calls.append(("double_click", (x, y)))

    def right_click(self, x, y):
        self.calls.append(("right_click", (x, y)))

    def hover(self, x, y):
        self.calls.append(("hover", (x, y)))

    def type_text(self, x, y, text):
        self.calls.append(("type_text", (x, y, text)))

    def clear_text(self, x, y):
        self.calls.append(("clear_text", (x, y)))

    def press_key(self, key):
        self.calls.append(("press_key", (key,)))

    def scroll(self, x, y, direction, distance):
        self.calls.append(("scroll", (x, y, direction, distance)))

    def drag(self, from_x, from_y, to_x, to_y):
        self.calls.append(("drag", (from_x, from_y, to_x, to_y)))

    def device_info(self):
        return DeviceInfo(platform="test", width=100, height=100)


class TestExecuteDispatch:
    def test_click(self):
        a = FakeAdapter()
        a.execute("click", {"x": 10, "y": 20})
        assert a.calls == [("click", (10.0, 20.0))]

    def test_double_click(self):
        a = FakeAdapter()
        a.execute("double_click", {"x": 10, "y": 20})
        assert a.calls == [("double_click", (10.0, 20.0))]

    def test_right_click(self):
        a = FakeAdapter()
        a.execute("right_click", {"x": 10, "y": 20})
        assert a.calls == [("right_click", (10.0, 20.0))]

    def test_hover(self):
        a = FakeAdapter()
        a.execute("hover", {"x": 10, "y": 20})
        assert a.calls == [("hover", (10.0, 20.0))]

    def test_type_text_basic(self):
        a = FakeAdapter()
        a.execute("type_text", {"x": 10, "y": 20, "text": "hello"})
        assert a.calls == [("type_text", (10.0, 20.0, "hello"))]

    def test_type_text_with_press_enter(self):
        a = FakeAdapter()
        a.execute("type_text", {"x": 10, "y": 20, "text": "hello", "press_enter": True})
        assert a.calls == [
            ("type_text", (10.0, 20.0, "hello")),
            ("press_key", ("Enter",)),
        ]

    def test_type_text_with_clear_before_typing(self):
        a = FakeAdapter()
        a.execute("type_text", {"x": 10, "y": 20, "text": "hello", "clear_before_typing": True})
        assert a.calls == [
            ("clear_text", (10.0, 20.0)),
            ("type_text", (10.0, 20.0, "hello")),
        ]

    def test_type_text_with_both_flags(self):
        a = FakeAdapter()
        a.execute("type_text", {
            "x": 10, "y": 20, "text": "hello",
            "clear_before_typing": True, "press_enter": True,
        })
        assert a.calls == [
            ("clear_text", (10.0, 20.0)),
            ("type_text", (10.0, 20.0, "hello")),
            ("press_key", ("Enter",)),
        ]

    def test_clear_text(self):
        a = FakeAdapter()
        a.execute("clear_text", {"x": 10, "y": 20})
        assert a.calls == [("clear_text", (10.0, 20.0))]

    def test_press_key(self):
        a = FakeAdapter()
        a.execute("press_key", {"key": "Enter"})
        assert a.calls == [("press_key", ("Enter",))]

    def test_scroll(self):
        a = FakeAdapter()
        a.execute("scroll", {"x": 0, "y": 0, "direction": "down", "distance": 300})
        assert a.calls == [("scroll", (0.0, 0.0, "down", 300))]

    def test_scroll_at(self):
        a = FakeAdapter()
        a.execute("scroll_at", {"x": 50, "y": 60, "direction": "up", "distance": 200})
        assert a.calls == [("scroll", (50.0, 60.0, "up", 200))]

    def test_drag(self):
        a = FakeAdapter()
        a.execute("drag", {"start_x": 10, "start_y": 20, "end_x": 100, "end_y": 200})
        assert a.calls == [("drag", (10.0, 20.0, 100.0, 200.0))]

    def test_wait_is_noop(self):
        a = FakeAdapter()
        a.execute("wait", {"duration": 1000})
        assert a.calls == []

    def test_done_is_noop(self):
        a = FakeAdapter()
        a.execute("done", {"success": True, "result": "ok"})
        assert a.calls == []

    def test_save_note_is_noop(self):
        a = FakeAdapter()
        a.execute("save_note", {"content": "test"})
        assert a.calls == []

    def test_unknown_action_raises(self):
        a = FakeAdapter()
        with pytest.raises(ValueError, match="Unknown action type"):
            a.execute("nonexistent", {})


def _fake_pyautogui(*, screenshot_w: int, logical_w: int, logical_h: int | None = None):
    """Build a MagicMock standing in for the pyautogui module.

    screenshot().width / size().width drives the adapter's scale factor probe.
    """
    pag = MagicMock()
    pag.__name__ = "pyautogui"
    shot = MagicMock()
    shot.width = screenshot_w
    shot.height = (logical_h or logical_w) * (screenshot_w // logical_w)
    pag.screenshot.return_value = shot
    size = MagicMock()
    size.width = logical_w
    size.height = logical_h or logical_w
    pag.size.return_value = size
    return pag


class TestPyAutoGuiScaling:
    def _adapter(self, **kw):
        from qirabot.adapters.pyautogui_adapter import PyAutoGuiAdapter

        return PyAutoGuiAdapter(_fake_pyautogui(**kw))

    def test_retina_click_halves_coordinates(self):
        a = self._adapter(screenshot_w=2880, logical_w=1440)
        a.click(446, 388)
        a._pag.click.assert_called_once_with(223, 194)

    def test_non_retina_click_passes_through(self):
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a.click(446, 389)
        a._pag.click.assert_called_once_with(446, 389)

    def test_scale_factor_is_cached(self):
        a = self._adapter(screenshot_w=2880, logical_w=1440)
        a.click(100, 100)
        a.click(200, 200)
        # One probe screenshot for the factor; clicks reuse the cache.
        assert a._pag.screenshot.call_count == 1

    def test_drag_scales_both_endpoints(self):
        a = self._adapter(screenshot_w=2880, logical_w=1440)
        a.drag(100, 100, 300, 500)
        a._pag.moveTo.assert_called_once_with(50, 50)
        # drag receives the logical delta: (150-50, 250-50)
        a._pag.drag.assert_called_once_with(100, 200, duration=0.5)

    def test_device_info_reports_physical_pixels_on_retina(self):
        # device_info must match the screenshot dimensions (physical), not
        # pyautogui's logical points, so callers that derive coordinates from it
        # (e.g. Qirabot.scroll's center anchor) stay in screenshot-pixel space.
        a = self._adapter(screenshot_w=2880, logical_w=1440, logical_h=900)
        info = a.device_info()
        assert (info.width, info.height) == (2880, 1800)

    def test_device_info_unchanged_on_non_retina(self):
        a = self._adapter(screenshot_w=1440, logical_w=1440, logical_h=900)
        info = a.device_info()
        assert (info.width, info.height) == (1440, 900)

    def test_ascii_text_uses_typewrite(self):
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a.type_text(10, 20, "hello")
        a._pag.typewrite.assert_called_once_with("hello", interval=0.02)

    def test_non_ascii_text_pastes_via_clipboard(self, monkeypatch):
        import sys

        fake_clip = MagicMock()
        monkeypatch.setitem(sys.modules, "pyperclip", fake_clip)
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a.type_text(10, 20, "儿子没给你打电话啊")
        fake_clip.copy.assert_called_once_with("儿子没给你打电话啊")
        a._pag.typewrite.assert_not_called()
        # paste hotkey fired with the platform modifier + 'v'
        assert a._pag.hotkey.call_args[0][-1] == "v"


class TestPlaywrightAdapterListener:
    """The adapter hooks the context's "page" event in __init__; close() must
    unhook it so the listener doesn't outlive the adapter and accumulate on the
    longer-lived context."""

    def test_close_removes_page_listener(self):
        from qirabot.adapters.playwright_adapter import PlaywrightAdapter

        page = MagicMock()
        context = MagicMock()
        page.context = context

        adapter = PlaywrightAdapter(page)
        assert context.on.call_count == 1
        event, handler = context.on.call_args.args
        assert event == "page"

        adapter.close()
        context.remove_listener.assert_called_once_with("page", handler)

    def test_close_swallows_remove_listener_errors(self):
        from qirabot.adapters.playwright_adapter import PlaywrightAdapter

        page = MagicMock()
        context = MagicMock()
        context.remove_listener.side_effect = Exception("context closed")
        page.context = context

        adapter = PlaywrightAdapter(page)
        adapter.close()  # must not raise even if the context is already gone
