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

    def test_scroll_amount_from_server(self):
        # The server sends distance as `amount` in pixels with no x/y; it must
        # be honored (converted to scroll units) rather than dropped to the
        # default of 3.
        a = FakeAdapter()
        a.execute("scroll", {"direction": "down", "amount": 500})
        assert a.calls == [("scroll", (0.0, 0.0, "down", 5))]

    def test_scroll_amount_rounds_up_to_one(self):
        a = FakeAdapter()
        a.execute("scroll", {"direction": "down", "amount": 30})
        assert a.calls == [("scroll", (0.0, 0.0, "down", 1))]

    def test_scroll_missing_amount_falls_back_to_default(self):
        a = FakeAdapter()
        a.execute("scroll", {"direction": "down"})
        assert a.calls == [("scroll", (0.0, 0.0, "down", 3))]

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
        a.type_text(10, 20, "打电话啊")
        fake_clip.copy.assert_called_once_with("打电话啊")
        a._pag.typewrite.assert_not_called()
        # paste hotkey fired with the platform modifier + 'v'
        assert a._pag.hotkey.call_args[0][-1] == "v"

    def test_scroll_without_xy_anchors_at_screen_center(self):
        # Server plain scroll sends no x/y -> 0,0; without the center fallback
        # the scroll would land on the top-left corner and do nothing.
        a = self._adapter(screenshot_w=1440, logical_w=1440, logical_h=900)
        a.scroll(0, 0, "down", 5)
        # center = (720, 450) in screenshot px == logical px here (scale 1.0)
        a._pag.scroll.assert_called_once_with(-15, x=720, y=450)

    def test_scroll_with_explicit_xy_is_respected(self):
        a = self._adapter(screenshot_w=1440, logical_w=1440, logical_h=900)
        a.scroll(100, 200, "up", 5)
        a._pag.scroll.assert_called_once_with(15, x=100, y=200)

    def test_server_scroll_path_honors_amount_and_centers(self):
        # End-to-end through execute(): {direction, amount} only, as the server
        # sends it. amount 500 -> distance 5 -> 15 clicks, centered.
        a = self._adapter(screenshot_w=1440, logical_w=1440, logical_h=900)
        a.execute("scroll", {"direction": "down", "amount": 500})
        a._pag.scroll.assert_called_once_with(-15, x=720, y=450)

    def test_screen_changing_action_settles(self, monkeypatch):
        import time

        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a.execute("click", {"x": 10, "y": 20})
        assert sleeps == [a._SETTLE_SECONDS]

    def test_no_settle_action_does_not_wait(self, monkeypatch):
        import time

        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a.execute("hover", {"x": 10, "y": 20})
        assert sleeps == []


class TestSeleniumAdapterSettle:
    """Selenium's coordinate actions don't wait for the effects they trigger, so
    execute() adds a fixed settle before the ai() loop screenshots again."""

    def _adapter(self):
        from qirabot.adapters.selenium_adapter import SeleniumAdapter

        return SeleniumAdapter(MagicMock())

    def test_screen_changing_action_settles(self, monkeypatch):
        import time

        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        a = self._adapter()
        # amount 500 -> distance 5 -> scrollBy 500px, then settle.
        a.execute("scroll", {"direction": "down", "amount": 500})
        a._driver.execute_script.assert_called_once_with("window.scrollBy(0, 500)")
        assert sleeps == [a._SETTLE_SECONDS]

    def test_no_settle_action_does_not_wait(self, monkeypatch):
        import time

        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        a = self._adapter()
        a.execute("done", {"success": True})
        assert sleeps == []


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


@pytest.fixture
def fake_airtest(monkeypatch):
    """Inject minimal fake ``airtest`` submodules the adapter lazily imports.

    Returns the ``NoDeviceError`` class so tests can both raise it (from the
    fake ``G.DEVICE``) and assert the adapter converts it to ``RuntimeError``.
    """
    import sys
    import types

    from PIL import Image

    class NoDeviceError(Exception):
        pass

    err_mod = types.ModuleType("airtest.core.error")
    err_mod.NoDeviceError = NoDeviceError

    utils_mod = types.ModuleType("airtest.aircv.utils")

    def cv2_2_pil(img):
        # Real impl converts a BGR ndarray -> RGB PIL; the tests don't care
        # about pixels, only that a sized PIL image flows through.
        return img if isinstance(img, Image.Image) else Image.new("RGB", (320, 640))

    utils_mod.cv2_2_pil = cv2_2_pil

    for name in ("airtest", "airtest.core", "airtest.aircv"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "airtest.core.error", err_mod)
    monkeypatch.setitem(sys.modules, "airtest.aircv.utils", utils_mod)
    return NoDeviceError


def _fake_device(platform="android", w=320, h=640, orientation=0):
    dev = MagicMock()
    dev.platform = platform
    dev.get_current_resolution.return_value = (w, h)
    dev.snapshot.return_value = "<bgr-ndarray>"  # cv2_2_pil fake ignores it
    # Real airtest exposes display_info as a dict; without this the MagicMock
    # makes int(display_info.get("orientation")) == 1, spuriously triggering the
    # landscape-rotation path in AirtestAdapter._ensure_upright.
    dev.display_info = {"orientation": orientation, "width": w, "height": h}
    return dev


def _fake_G(holder, no_device_error):
    """A stand-in for airtest's ``G`` (a class with a metaclass ``DEVICE`` prop).

    ``holder`` is a 1-element list so a test can swap the current device
    (``set_current`` semantics) or set it to ``None`` (no device connected).
    """

    class GMeta(type):
        @property
        def DEVICE(cls):
            if holder[0] is None:
                raise no_device_error("No devices added.")
            return holder[0]

    class G(metaclass=GMeta):
        pass

    G.__module__ = "airtest.core.helper"
    return G


class TestAirtestAdapter:
    def _adapter(self, target):
        from qirabot.adapters.airtest_adapter import AirtestAdapter

        return AirtestAdapter(target)

    def test_lazy_resolution_via_G(self, fake_airtest):
        dev = _fake_device()
        G = _fake_G([dev], fake_airtest)
        a = self._adapter(G)
        a.click(10, 20)
        dev.touch.assert_called_once_with((10, 20))
        # current_target stays the original token, not a concrete device.
        assert a.current_target is G

    def test_lazy_resolution_follows_set_current(self, fake_airtest):
        dev1, dev2 = _fake_device(), _fake_device()
        holder = [dev1]
        G = _fake_G(holder, fake_airtest)
        a = self._adapter(G)
        a.click(1, 2)
        dev1.touch.assert_called_once_with((1, 2))
        holder[0] = dev2  # set_current(...) switched the active device
        a.click(3, 4)
        dev2.touch.assert_called_once_with((3, 4))
        assert dev1.touch.call_count == 1  # old device untouched after switch

    def test_accepts_G_when_no_device_connected(self, fake_airtest):
        # #1 regression: accepts() must NOT touch G.DEVICE (metaclass property
        # that raises NoDeviceError before a device is connected).
        from qirabot.adapters.airtest_adapter import AirtestAdapter

        G = _fake_G([None], fake_airtest)
        assert AirtestAdapter.accepts(G) is True  # must not raise

    def test_no_device_raises_friendly_runtime_error(self, fake_airtest):
        # #2 regression: NoDeviceError -> friendly RuntimeError.
        G = _fake_G([None], fake_airtest)
        a = self._adapter(G)
        with pytest.raises(RuntimeError, match="no current airtest device"):
            a.click(1, 2)

    def test_accepts_variants(self, fake_airtest):
        import types

        from qirabot.adapters.airtest_adapter import AirtestAdapter

        class FakeDevice:
            def snapshot(self):
                return None

            def get_current_resolution(self):
                return (100, 100)

        FakeDevice.__module__ = "airtest.core.android.android"

        class FakeTemplate:  # same package, but not a device
            pass

        FakeTemplate.__module__ = "airtest.core.cv"

        api_mod = types.ModuleType("airtest.core.api")

        assert AirtestAdapter.accepts(FakeDevice()) is True
        assert AirtestAdapter.accepts(_fake_G([None], fake_airtest)) is True
        assert AirtestAdapter.accepts(api_mod) is True
        assert AirtestAdapter.accepts(object()) is False
        assert AirtestAdapter.accepts(FakeTemplate()) is False

    def test_click_and_type_text(self, fake_airtest):
        dev = _fake_device()
        a = self._adapter(dev)
        a.type_text(5, 6, "hi")
        dev.touch.assert_called_once_with((5, 6))
        dev.text.assert_called_once_with("hi", enter=False)

    def test_press_key_maps_to_keyevent(self, fake_airtest):
        dev = _fake_device()
        a = self._adapter(dev)
        a.press_key("Enter")
        dev.keyevent.assert_called_once_with("ENTER")

    def test_press_key_passthrough_unknown(self, fake_airtest):
        dev = _fake_device()
        a = self._adapter(dev)
        a.press_key("VOLUME_UP")
        dev.keyevent.assert_called_once_with("VOLUME_UP")

    def test_scroll_via_execute_calls_swipe(self, fake_airtest):
        dev = _fake_device(w=400, h=800)
        a = self._adapter(dev)
        a.execute("scroll", {"direction": "down", "amount": 300})
        assert dev.swipe.call_count == 1
        (p1, p2), kwargs = dev.swipe.call_args
        # down: end y is above the start y (smaller), x unchanged at center.
        assert p1 == (200, 400)
        assert p2[0] == 200 and p2[1] < p1[1]

    def test_device_info_uses_last_screenshot_size(self, fake_airtest):
        dev = _fake_device(platform="android")
        a = self._adapter(dev)
        a.screenshot()  # fake cv2_2_pil yields a 320x640 image
        info = a.device_info()
        assert (info.platform, info.width, info.height) == ("android", 320, 640)

    def test_device_info_platform_mapping_windows(self, fake_airtest):
        dev = _fake_device(platform="windows", w=1920, h=1080)
        a = self._adapter(dev)
        info = a.device_info()  # no screenshot -> get_current_resolution
        assert (info.platform, info.width, info.height) == ("desktop", 1920, 1080)

    def test_screenshot_returns_bytes_and_caches_size(self, fake_airtest):
        dev = _fake_device()
        a = self._adapter(dev)
        data = a.screenshot()
        assert isinstance(data, bytes) and len(data) > 0
        assert a._last_size == (320, 640)

    def test_screen_changing_action_settles(self, fake_airtest, monkeypatch):
        import time

        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        a = self._adapter(_fake_device())
        a.execute("click", {"x": 1, "y": 2})
        assert sleeps == [a._SETTLE_SECONDS]

    def test_no_settle_action_does_not_wait(self, fake_airtest, monkeypatch):
        import time

        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        a = self._adapter(_fake_device())
        a.execute("hover", {"x": 1, "y": 2})
        assert sleeps == []


class TestBind:
    def _bound(self, bot):
        from qirabot.client import _BoundQirabot

        return _BoundQirabot(bot, "T")

    def test_click_injects_target(self):
        bot = MagicMock()
        bot.click.return_value = "T"
        self._bound(bot).click("Login", retry=2)
        bot.click.assert_called_once_with(
            "T", "Login", timeout=0.0, interval=2.0, wait="", retry=2, model_alias="", language=""
        )

    def test_type_text_injects_target(self):
        bot = MagicMock()
        bot.type_text.return_value = "T"
        self._bound(bot).type_text("Email", "a@b.com", press_enter=True)
        bot.type_text.assert_called_once_with(
            "T",
            "Email",
            "a@b.com",
            press_enter=True,
            clear_before_typing=False,
            timeout=0.0,
            interval=2.0,
            wait="",
            retry=None,
            model_alias="",
            language="",
        )

    def test_auto_rebind_follows_returned_target(self):
        bot = MagicMock()
        bot.click.return_value = "NEW_PAGE"
        b = self._bound(bot)
        assert b.click("x") == "NEW_PAGE"
        assert b._target == "NEW_PAGE"
        b.click("y")  # next call uses the new target
        assert bot.click.call_args_list[-1].args[0] == "NEW_PAGE"

    def test_non_rebinding_method_keeps_target(self):
        bot = MagicMock()
        bot.extract.return_value = "text"
        b = self._bound(bot)
        assert b.extract("get title") == "text"
        assert b._target == "T"  # extract doesn't re-bind

    def test_lifecycle_explicit_delegation(self):
        bot = MagicMock()
        bot.task_id = "task-123"
        b = self._bound(bot)
        b.close()
        bot.close.assert_called_once_with()
        assert b.task_id == "task-123"

    def test_unknown_attr_delegates_via_getattr(self):
        bot = MagicMock()
        b = self._bound(bot)
        b.launch_app("WeChat", wait=3)
        bot.launch_app.assert_called_once_with("WeChat", wait=3)

    def test_context_manager_delegates_and_returns_self(self):
        bot = MagicMock()
        b = self._bound(bot)
        with b as entered:
            assert entered is b
        bot.__enter__.assert_called_once()
        bot.__exit__.assert_called_once()

    def test_bind_parity_covers_all_target_methods(self):
        import inspect

        from qirabot.client import Qirabot, _BoundQirabot

        for name in dir(Qirabot):
            if name.startswith("_") or name == "bind":
                continue  # bind() takes a target but creates the proxy, not proxied
            attr = inspect.getattr_static(Qirabot, name)
            if not inspect.isfunction(attr):
                continue
            params = list(inspect.signature(attr).parameters)
            if len(params) >= 2 and params[1] == "target":
                assert hasattr(_BoundQirabot, name), f"facade missing proxy for {name}"
