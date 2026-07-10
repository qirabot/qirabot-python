"""Tests for adapter base execute() dispatch logic."""

import importlib.util
from unittest.mock import MagicMock, call

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

    def long_press(self, x, y, duration=2.0):
        self.calls.append(("long_press", (x, y, duration)))

    def mouse_down(self, x, y):
        self.calls.append(("mouse_down", (x, y)))

    def mouse_up(self, x=None, y=None):
        self.calls.append(("mouse_up", (x, y)))

    def key_down(self, key):
        self.calls.append(("key_down", (key,)))

    def key_up(self, key):
        self.calls.append(("key_up", (key,)))

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

    def test_long_press_default_duration(self):
        a = FakeAdapter()
        a.execute("long_press", {"x": 10, "y": 20})
        # No duration on the wire -> 2000ms default -> 2.0s.
        assert a.calls == [("long_press", (10.0, 20.0, 2.0))]

    def test_long_press_converts_ms_to_seconds(self):
        a = FakeAdapter()
        a.execute("long_press", {"x": 10, "y": 20, "duration": 600})
        assert a.calls == [("long_press", (10.0, 20.0, 0.6))]

    def test_mouse_down(self):
        a = FakeAdapter()
        a.execute("mouse_down", {"x": 10, "y": 20})
        assert a.calls == [("mouse_down", (10.0, 20.0))]

    def test_mouse_up_with_coords(self):
        a = FakeAdapter()
        a.execute("mouse_up", {"x": 10, "y": 20})
        # locate resolved -> release at the target point.
        assert a.calls == [("mouse_up", (10.0, 20.0))]

    def test_mouse_up_without_coords_releases_at_cursor(self):
        a = FakeAdapter()
        a.execute("mouse_up", {})
        # no x/y on the wire -> release at the current cursor (None, None).
        assert a.calls == [("mouse_up", (None, None))]

    def test_key_down(self):
        a = FakeAdapter()
        a.execute("key_down", {"key": "w"})
        assert a.calls == [("key_down", ("w",))]

    def test_key_up(self):
        a = FakeAdapter()
        a.execute("key_up", {"key": "w"})
        assert a.calls == [("key_up", ("w",))]

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


class TestPressKeyHeld:
    """press_key with duration_seconds: hold via key_down/key_up, degrade to a
    tap where the split primitives are missing, never leave a key stuck."""

    @pytest.fixture
    def sleeps(self, monkeypatch):
        recorded: list[float] = []
        monkeypatch.setattr("time.sleep", lambda s: recorded.append(s))
        return recorded

    def test_hold_single_key(self, sleeps):
        a = FakeAdapter()
        a.execute("press_key", {"key": "w", "duration_seconds": 2})
        assert a.calls == [("key_down", ("w",)), ("key_up", ("w",))]
        assert sleeps == [2.0]

    def test_hold_combo_wraps_modifiers(self, sleeps):
        a = FakeAdapter()
        a.execute("press_key", {"key": "shift+w", "duration_seconds": 1.5})
        assert a.calls == [
            ("key_down", ("shift",)),
            ("key_down", ("w",)),
            ("key_up", ("w",)),
            ("key_up", ("shift",)),
        ]
        assert sleeps == [1.5]

    def test_duration_clamped_to_ten_seconds(self, sleeps):
        a = FakeAdapter()
        a.execute("press_key", {"key": "w", "duration_seconds": 30})
        assert sleeps == [10.0]

    @pytest.mark.parametrize("duration", [0, None, "", "abc", -1])
    def test_zero_missing_or_dirty_duration_taps(self, sleeps, duration):
        a = FakeAdapter()
        params = {"key": "Enter"}
        if duration is not None:
            params["duration_seconds"] = duration
        a.execute("press_key", params)
        assert a.calls == [("press_key", ("Enter",))]
        assert sleeps == []

    def test_degrades_to_tap_without_key_down(self, sleeps):
        class NoHoldAdapter(FakeAdapter):
            def key_down(self, key):
                raise NotImplementedError

        a = NoHoldAdapter()
        a.execute("press_key", {"key": "shift+w", "duration_seconds": 2})
        assert a.calls == [("press_key", ("shift+w",))]
        assert sleeps == []

    def test_exception_during_hold_releases_pressed_keys(self, monkeypatch):
        def boom(_):
            raise RuntimeError("interrupted")

        monkeypatch.setattr("time.sleep", boom)
        a = FakeAdapter()
        with pytest.raises(RuntimeError, match="interrupted"):
            a.execute("press_key", {"key": "shift+w", "duration_seconds": 2})
        assert a.calls == [
            ("key_down", ("shift",)),
            ("key_down", ("w",)),
            ("key_up", ("w",)),
            ("key_up", ("shift",)),
        ]

    def test_failed_release_sweeps_all_inputs(self, sleeps):
        class StuckKeyAdapter(FakeAdapter):
            def key_up(self, key):
                raise RuntimeError("stuck")

            def release_all_inputs(self):
                self.calls.append(("release_all_inputs", ()))

        a = StuckKeyAdapter()
        a.execute("press_key", {"key": "w", "duration_seconds": 1})
        assert a.calls == [("key_down", ("w",)), ("release_all_inputs", ())]


class TestClickWithModifiers:
    """click with modifier: hold modifier key(s) around the click via
    key_down/key_up, degrade to a plain click where the split primitives are
    missing, never leave a modifier stuck."""

    @pytest.fixture
    def sleeps(self, monkeypatch):
        recorded: list[float] = []
        monkeypatch.setattr("time.sleep", lambda s: recorded.append(s))
        return recorded

    def test_single_modifier_wraps_click(self, sleeps):
        a = FakeAdapter()
        a.execute("click", {"x": 10, "y": 20, "modifier": "alt"})
        assert a.calls == [
            ("key_down", ("alt",)),
            ("click", (10.0, 20.0)),
            ("key_up", ("alt",)),
        ]
        # Guard sleeps before and after the click so frame-polling apps
        # sample the modifier as held through the whole button press.
        assert sleeps == [0.05, 0.05]

    def test_combo_modifiers_release_in_reverse(self, sleeps):
        a = FakeAdapter()
        a.execute("click", {"x": 10, "y": 20, "modifier": "ctrl+shift"})
        assert a.calls == [
            ("key_down", ("ctrl",)),
            ("key_down", ("shift",)),
            ("click", (10.0, 20.0)),
            ("key_up", ("shift",)),
            ("key_up", ("ctrl",)),
        ]

    @pytest.mark.parametrize("modifier", [None, "", "  "])
    def test_missing_or_blank_modifier_plain_click(self, sleeps, modifier):
        a = FakeAdapter()
        params = {"x": 10, "y": 20}
        if modifier is not None:
            params["modifier"] = modifier
        a.execute("click", params)
        assert a.calls == [("click", (10.0, 20.0))]
        assert sleeps == []

    def test_degrades_to_plain_click_without_key_down(self, sleeps):
        class NoHoldAdapter(FakeAdapter):
            def key_down(self, key):
                raise NotImplementedError

        a = NoHoldAdapter()
        a.execute("click", {"x": 10, "y": 20, "modifier": "alt"})
        assert a.calls == [("click", (10.0, 20.0))]
        assert sleeps == []

    def test_click_failure_releases_pressed_modifiers(self, sleeps):
        class BoomClickAdapter(FakeAdapter):
            def click(self, x, y):
                raise RuntimeError("click failed")

        a = BoomClickAdapter()
        with pytest.raises(RuntimeError, match="click failed"):
            a.execute("click", {"x": 10, "y": 20, "modifier": "ctrl+shift"})
        assert a.calls == [
            ("key_down", ("ctrl",)),
            ("key_down", ("shift",)),
            ("key_up", ("shift",)),
            ("key_up", ("ctrl",)),
        ]

    def test_failed_release_sweeps_all_inputs(self, sleeps):
        class StuckKeyAdapter(FakeAdapter):
            def key_up(self, key):
                raise RuntimeError("stuck")

            def release_all_inputs(self):
                self.calls.append(("release_all_inputs", ()))

        a = StuckKeyAdapter()
        a.execute("click", {"x": 10, "y": 20, "modifier": "alt"})
        assert a.calls == [
            ("key_down", ("alt",)),
            ("click", (10.0, 20.0)),
            ("release_all_inputs", ()),
        ]


class TestSettleOverride:
    """settle_seconds resolution: instance override beats the class default,
    and a screen-changing action sleeps that effective value."""

    def test_default_is_class_constant(self):
        a = FakeAdapter()
        assert a.settle_seconds == FakeAdapter._SETTLE_SECONDS

    def test_override_takes_precedence(self):
        a = FakeAdapter()
        a._SETTLE_SECONDS = 0.6  # pretend a platform default
        a._settle_override = 0.2
        assert a.settle_seconds == 0.2

    def test_override_zero_disables_settle(self, monkeypatch):
        import time

        a = FakeAdapter()
        a._SETTLE_SECONDS = 0.6
        a._settle_override = 0
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        a.execute("click", {"x": 1, "y": 2})
        assert sleeps == []  # 0 is falsy -> no sleep call

    def test_override_applied_on_screen_changing_action(self, monkeypatch):
        import time

        a = FakeAdapter()
        a._settle_override = 0.25
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        a.execute("click", {"x": 1, "y": 2})
        assert sleeps == [0.25]


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
        # drag receives the logical delta: (150-50, 250-50). button="left" is
        # required so pyautogui's default "primary" never reaches the macOS
        # backend's _dragTo() (which asserts left/middle/right).
        a._pag.drag.assert_called_once_with(100, 200, duration=0.5, button="left")

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

    def test_mouse_down_holds_button_scaled(self):
        a = self._adapter(screenshot_w=2880, logical_w=1440)
        a.mouse_down(200, 400)
        # 2x display -> screenshot-pixel coords halved to logical points.
        a._pag.mouseDown.assert_called_once_with(100, 200)
        assert a._mouse_held is True

    def test_mouse_up_with_coords(self):
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a._mouse_held = True
        a.mouse_up(50, 60)
        a._pag.mouseUp.assert_called_once_with(50, 60)
        assert a._mouse_held is False

    def test_mouse_up_without_coords_releases_at_cursor(self):
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a._mouse_held = True
        a.mouse_up()
        a._pag.mouseUp.assert_called_once_with()
        assert a._mouse_held is False

    def test_key_down_up_tracks_held(self):
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a.key_down("w")
        a._pag.keyDown.assert_called_once_with("w")
        assert a._held_keys == {"w"}
        a.key_up("w")
        a._pag.keyUp.assert_called_once_with("w")
        assert a._held_keys == set()

    def test_key_down_normalizes_name(self):
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a.key_down("ArrowUp")
        # _norm_key maps ArrowUp -> up before holding.
        a._pag.keyDown.assert_called_once_with("up")
        assert a._held_keys == {"up"}

    def test_release_all_inputs_releases_held_key_and_mouse(self):
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a.key_down("w")
        a.key_down("shift")
        a.mouse_down(10, 20)
        a.release_all_inputs()
        # every held key released, mouse released at current cursor, state cleared.
        released = {c.args[0] for c in a._pag.keyUp.call_args_list}
        assert released == {"w", "shift"}
        a._pag.mouseUp.assert_called_once_with()
        assert a._held_keys == set()
        assert a._mouse_held is False

    def test_release_all_inputs_noop_when_nothing_held(self):
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a.release_all_inputs()
        a._pag.keyUp.assert_not_called()
        a._pag.mouseUp.assert_not_called()

    # pyautogui.scroll()'s unit is platform-dependent, so every scroll test pins
    # platform.system() — otherwise the expected click count flips with the OS
    # the suite runs on. macOS: lines (~3/notch); Windows: raw wheel delta
    # (120/notch); X11: one click/notch.
    @staticmethod
    def _pin_platform(monkeypatch, name):
        monkeypatch.setattr(
            "qirabot.adapters.pyautogui_adapter.platform.system", lambda: name
        )

    def test_scroll_without_xy_anchors_at_screen_center(self, monkeypatch):
        # Server plain scroll sends no x/y -> 0,0; without the center fallback
        # the scroll would land on the top-left corner and do nothing.
        self._pin_platform(monkeypatch, "Darwin")
        a = self._adapter(screenshot_w=1440, logical_w=1440, logical_h=900)
        a.scroll(0, 0, "down", 5)
        # macOS unit is lines (~3/notch): 5 notches -> 15 lines, centered.
        # center = (720, 450) in screenshot px == logical px here (scale 1.0)
        a._pag.scroll.assert_called_once_with(-15, x=720, y=450)

    def test_scroll_with_explicit_xy_is_respected(self, monkeypatch):
        self._pin_platform(monkeypatch, "Darwin")
        a = self._adapter(screenshot_w=1440, logical_w=1440, logical_h=900)
        a.scroll(100, 200, "up", 5)
        a._pag.scroll.assert_called_once_with(15, x=100, y=200)

    def test_server_scroll_path_honors_amount_and_centers(self, monkeypatch):
        # End-to-end through execute(): {direction, amount} only, as the server
        # sends it. amount 500 -> distance 5 -> 15 lines on macOS, centered.
        self._pin_platform(monkeypatch, "Darwin")
        a = self._adapter(screenshot_w=1440, logical_w=1440, logical_h=900)
        a.execute("scroll", {"direction": "down", "amount": 500})
        a._pag.scroll.assert_called_once_with(-15, x=720, y=450)

    def test_scroll_macos_does_not_move_cursor(self, monkeypatch):
        # macOS _scroll anchors at x/y itself, so the adapter must NOT moveTo.
        self._pin_platform(monkeypatch, "Darwin")
        a = self._adapter(screenshot_w=1440, logical_w=1440, logical_h=900)
        a.scroll(100, 200, "down", 5)
        a._pag.moveTo.assert_not_called()

    def test_scroll_windows_uses_wheel_delta_and_moves_first(self, monkeypatch):
        # Windows scroll() takes a raw wheel delta (120 == one notch) and ignores
        # x/y (no MOVE flag), so the adapter must scale by 120 AND move the cursor
        # to the anchor first, or the wheel lands wherever the cursor happens to be.
        self._pin_platform(monkeypatch, "Windows")
        a = self._adapter(screenshot_w=1440, logical_w=1440, logical_h=900)
        a.scroll(100, 200, "up", 5)
        a._pag.moveTo.assert_called_once_with(100, 200)
        a._pag.scroll.assert_called_once_with(600, x=100, y=200)  # 5 * 120

    def test_scroll_windows_horizontal_scales_and_signs(self, monkeypatch):
        self._pin_platform(monkeypatch, "Windows")
        a = self._adapter(screenshot_w=1440, logical_w=1440, logical_h=900)
        a.scroll(100, 200, "right", 5)
        a._pag.hscroll.assert_called_once_with(600, x=100, y=200)

    def test_scroll_linux_uses_one_click_per_notch(self, monkeypatch):
        # X11 scroll() is one wheel click (notch) per unit and already anchors at
        # x/y inside its own _scroll, so no 120x scaling and no extra moveTo.
        self._pin_platform(monkeypatch, "Linux")
        a = self._adapter(screenshot_w=1440, logical_w=1440, logical_h=900)
        a.scroll(100, 200, "down", 5)
        a._pag.scroll.assert_called_once_with(-5, x=100, y=200)
        a._pag.moveTo.assert_not_called()

    def test_press_key_single_special_is_normalized(self):
        # "Enter"/"ArrowDown" aren't pyautogui key names; press() would no-op.
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a.press_key("Enter")
        a._pag.press.assert_called_once_with("enter")
        a._pag.hotkey.assert_not_called()

    def test_press_key_arrow_normalized(self):
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a.press_key("ArrowDown")
        a._pag.press.assert_called_once_with("down")

    def test_press_key_combo_uses_hotkey(self):
        # press() can't do combos; "ctrl+c" must go through hotkey().
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a.press_key("ctrl+c")
        a._pag.hotkey.assert_called_once_with("ctrl", "c")
        a._pag.press.assert_not_called()

    def test_press_key_alt_tab_combo(self):
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a.press_key("alt+tab")
        a._pag.hotkey.assert_called_once_with("alt", "tab")

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
        a.execute("save_note", {"content": "x"})
        assert sleeps == []

    def test_hover_settles(self, monkeypatch):
        # hover reveals delayed UI (tooltip/submenu), so it must settle before the
        # next screenshot — it is NOT a _NO_SETTLE action.
        import time

        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        a = self._adapter(screenshot_w=1440, logical_w=1440)
        a.execute("hover", {"x": 10, "y": 20})
        assert sleeps == [a._SETTLE_SECONDS]


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


class TestSeleniumPressKey:
    """send_keys() treats its argument as literal text, so combos and special
    keys must be mapped to Keys.* and held modifiers via ActionChains."""

    # Unlike the other selenium tests (which drive a MagicMock driver), these
    # reach into the real selenium package for Keys/ActionChains. selenium is an
    # optional backend not installed in CI, so skip rather than error there.
    pytestmark = pytest.mark.skipif(
        importlib.util.find_spec("selenium") is None,
        reason="selenium is an optional backend; not installed",
    )

    def _adapter(self):
        from qirabot.adapters.selenium_adapter import SeleniumAdapter

        return SeleniumAdapter(MagicMock())

    def _patch_action_chains(self, monkeypatch):
        import selenium.webdriver.common.action_chains as acm

        fake = MagicMock()
        monkeypatch.setattr(acm, "ActionChains", fake)
        return fake

    def test_combo_holds_modifier(self, monkeypatch):
        from selenium.webdriver.common.keys import Keys

        fake = self._patch_action_chains(monkeypatch)
        self._adapter().press_key("ctrl+a")
        inst = fake.return_value
        inst.key_down.assert_called_once_with(Keys.CONTROL)
        inst.send_keys.assert_called_once_with("a")
        inst.key_up.assert_called_once_with(Keys.CONTROL)
        inst.perform.assert_called_once()

    def test_special_key_maps_to_keys_enum(self, monkeypatch):
        from selenium.webdriver.common.keys import Keys

        fake = self._patch_action_chains(monkeypatch)
        self._adapter().press_key("Enter")
        inst = fake.return_value
        inst.key_down.assert_not_called()
        inst.send_keys.assert_called_once_with(Keys.ENTER)
        inst.perform.assert_called_once()


class TestAirtestWindowInfo:
    """window_info() identifies the window under test for per-window recording:
    Windows only; other platforms and unidentifiable/unconnected devices -> None."""

    def _adapter(self, platform: str):
        from qirabot.adapters.airtest_adapter import AirtestAdapter

        dev = MagicMock()  # snapshot/get_current_resolution -> concrete-device path
        dev.platform = platform
        return AirtestAdapter(dev), dev

    def test_windows_returns_title_and_handle(self):
        a, dev = self._adapter("windows")
        dev.handle = 12345
        dev.get_title.return_value = ["My App"]  # airtest returns list[str]
        assert a.window_info() == {"title": "My App", "hwnd": 12345}

    def test_non_windows_returns_none(self):
        a, _ = self._adapter("android")
        assert a.window_info() is None

    def test_windows_handle_only_when_title_unavailable(self):
        a, dev = self._adapter("windows")
        dev.handle = 999
        dev.get_title.side_effect = RuntimeError("not connected")  # @require_app
        assert a.window_info() == {"title": None, "hwnd": 999}

    def test_windows_none_when_nothing_identifiable(self):
        a, dev = self._adapter("windows")
        dev.handle = None
        dev.get_title.side_effect = RuntimeError("not connected")
        assert a.window_info() is None


class TestAirtestPressKey:
    """Windows prefers the DirectInput scancode path (key_press/key_release) so
    games receive the keys; only keys the scancode table can't express fall back
    to pywinauto SendKeys. Android/iOS use adb keycode names. Verifies the
    routing per platform, not pywinauto/adb themselves."""

    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch):
        # The scancode path paces keys with real sleeps; skip them in tests.
        monkeypatch.setattr("time.sleep", lambda s: None)

    def _adapter(self, platform: str):
        from qirabot.adapters.airtest_adapter import AirtestAdapter

        dev = MagicMock()  # has snapshot/get_current_resolution -> concrete-device path
        dev.platform = platform
        return AirtestAdapter(dev), dev

    @staticmethod
    def _key_calls(dev):
        # The DirectInput path drives key_press/key_release on the device; pull
        # them out (in order) so the interleaving of downs/ups is asserted.
        return [c for c in dev.method_calls if c[0] in ("key_press", "key_release")]

    def test_windows_backtick_uses_scancode(self):
        # Regression: the ` game-console key must go through scancodes; SendKeys
        # sends a virtual key the game's DirectInput never sees.
        a, dev = self._adapter("windows")
        a.press_key("`")
        dev.keyevent.assert_not_called()
        assert self._key_calls(dev) == [
            call.key_press("`"),
            call.key_release("`"),
        ]

    def test_windows_letter_uses_scancode(self):
        # WASD movement: a bare letter must reach the game as a scancode.
        a, dev = self._adapter("windows")
        a.press_key("w")
        dev.keyevent.assert_not_called()
        assert self._key_calls(dev) == [
            call.key_press("W"),
            call.key_release("W"),
        ]

    def test_windows_combo_uses_scancode(self):
        a, dev = self._adapter("windows")
        a.press_key("ctrl+c")
        dev.keyevent.assert_not_called()
        assert self._key_calls(dev) == [
            call.key_press("LCTRL"),
            call.key_press("C"),
            call.key_release("C"),
            call.key_release("LCTRL"),
        ]

    def test_windows_alt_tab(self):
        a, dev = self._adapter("windows")
        a.press_key("alt+tab")
        dev.keyevent.assert_not_called()
        assert self._key_calls(dev) == [
            call.key_press("LALT"),
            call.key_press("TAB"),
            call.key_release("TAB"),
            call.key_release("LALT"),
        ]

    def test_windows_single_special_uses_scancode(self):
        a, dev = self._adapter("windows")
        a.press_key("Enter")
        dev.keyevent.assert_not_called()
        assert self._key_calls(dev) == [
            call.key_press("ENTER"),
            call.key_release("ENTER"),
        ]

    def test_windows_function_key_uses_scancode(self):
        a, dev = self._adapter("windows")
        a.press_key("f5")
        dev.keyevent.assert_not_called()
        assert self._key_calls(dev) == [
            call.key_press("F5"),
            call.key_release("F5"),
        ]

    def test_windows_alt_f4_uses_scancode(self):
        a, dev = self._adapter("windows")
        a.press_key("alt+f4")
        dev.keyevent.assert_not_called()
        assert self._key_calls(dev) == [
            call.key_press("LALT"),
            call.key_press("F4"),
            call.key_release("F4"),
            call.key_release("LALT"),
        ]

    def test_windows_arrow_name_uses_scancode(self):
        # The model may emit "Down" or "ArrowDown"; both normalize to DOWN.
        a, dev = self._adapter("windows")
        a.press_key("down")
        dev.keyevent.assert_not_called()
        assert self._key_calls(dev) == [
            call.key_press("DOWN"),
            call.key_release("DOWN"),
        ]

    def test_windows_win_combo_uses_down_up(self):
        # SendKeys' ^%+ prefixes can't express Win; the scancode path injects the
        # real LWINDOWS the shell hotkeys need.
        a, dev = self._adapter("windows")
        a.press_key("win+d")
        dev.keyevent.assert_not_called()
        assert self._key_calls(dev) == [
            call.key_press("LWINDOWS"),
            call.key_press("D"),
            call.key_release("D"),
            call.key_release("LWINDOWS"),
        ]

    def test_windows_bare_win_opens_start(self):
        # Bare Win is a press+release of LWINDOWS (taps Start).
        a, dev = self._adapter("windows")
        a.press_key("win")
        dev.keyevent.assert_not_called()
        assert self._key_calls(dev) == [
            call.key_press("LWINDOWS"),
            call.key_release("LWINDOWS"),
        ]

    def test_windows_combo_nests_and_releases_in_reverse(self):
        # Mods nest in order and release in reverse; the base reuses the scancode
        # map (server sends JS-style "arrowleft", not "left").
        a, dev = self._adapter("windows")
        a.press_key("ctrl+win+arrowleft")
        dev.keyevent.assert_not_called()
        assert self._key_calls(dev) == [
            call.key_press("LCTRL"),
            call.key_press("LWINDOWS"),
            call.key_press("LEFT"),
            call.key_release("LEFT"),
            call.key_release("LWINDOWS"),
            call.key_release("LCTRL"),
        ]

    def test_windows_unsupported_key_falls_back_to_sendkeys(self):
        # A shifted symbol isn't in the scancode table, so it falls back to
        # SendKeys (which types it correctly) with no scancode calls.
        a, dev = self._adapter("windows")
        a.press_key("!")
        assert self._key_calls(dev) == []
        dev.keyevent.assert_called_once_with("!")

    def test_android_single_key_is_adb_keycode(self):
        a, dev = self._adapter("android")
        a.press_key("Enter")
        dev.keyevent.assert_called_once_with("ENTER")


class TestAirtestTypeText:
    """Windows types ASCII via DirectInput scancodes so games receive the text;
    non-ASCII (or any unmappable char) falls the whole string back to
    device.text() (SendKeys). Other platforms always use device.text()."""

    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch):
        # type_text paces keys and settles focus with real sleeps; skip in tests.
        monkeypatch.setattr("time.sleep", lambda s: None)

    def _adapter(self, platform: str):
        from qirabot.adapters.airtest_adapter import AirtestAdapter

        dev = MagicMock()  # has snapshot/get_current_resolution -> concrete-device path
        dev.platform = platform
        return AirtestAdapter(dev), dev

    @staticmethod
    def _key_calls(dev):
        return [c for c in dev.method_calls if c[0] in ("key_press", "key_release")]

    def test_windows_ascii_uses_scancodes(self):
        a, dev = self._adapter("windows")
        a.type_text(10, 20, "ab 1")
        dev.touch.assert_called_once_with((10, 20))  # caret placement first
        dev.text.assert_not_called()
        assert self._key_calls(dev) == [
            call.key_press("A"), call.key_release("A"),
            call.key_press("B"), call.key_release("B"),
            call.key_press("SPACE"), call.key_release("SPACE"),
            call.key_press("1"), call.key_release("1"),
        ]

    def test_windows_shifted_chars_hold_shift(self):
        a, dev = self._adapter("windows")
        a.type_text(0, 0, "A!")
        dev.text.assert_not_called()
        assert self._key_calls(dev) == [
            call.key_press("LSHIFT"), call.key_press("A"),
            call.key_release("A"), call.key_release("LSHIFT"),
            call.key_press("LSHIFT"), call.key_press("1"),
            call.key_release("1"), call.key_release("LSHIFT"),
        ]

    def test_windows_game_command_uses_scancodes(self):
        # The reported case: a chat/console command must reach the game.
        a, dev = self._adapter("windows")
        a.type_text(0, 0, "quest accept 7011402")
        dev.text.assert_not_called()
        assert self._key_calls(dev)[:2] == [call.key_press("Q"), call.key_release("Q")]
        assert len(self._key_calls(dev)) == 2 * len("quest accept 7011402")

    def test_windows_non_ascii_falls_back_to_sendkeys(self):
        a, dev = self._adapter("windows")
        a.type_text(0, 0, "打电话")
        assert self._key_calls(dev) == []
        dev.text.assert_called_once_with("打电话", enter=False)

    def test_windows_mixed_ascii_and_non_ascii_falls_back_whole(self):
        # One non-ASCII char makes the WHOLE string take the SendKeys path.
        a, dev = self._adapter("windows")
        a.type_text(0, 0, "hi打")
        assert self._key_calls(dev) == []
        dev.text.assert_called_once_with("hi打", enter=False)

    def test_android_uses_device_text(self):
        a, dev = self._adapter("android")
        a.type_text(0, 0, "hello")
        assert self._key_calls(dev) == []
        dev.text.assert_called_once_with("hello", enter=False)


class TestAirtestHover:
    """Hover is a cursor concept: Windows moves the cursor (mouse_move, NOT the
    window-moving device.move); touch platforms keep the base no-op."""

    def _adapter(self, platform: str):
        from qirabot.adapters.airtest_adapter import AirtestAdapter

        dev = MagicMock()  # has snapshot/get_current_resolution -> concrete-device path
        dev.platform = platform
        return AirtestAdapter(dev), dev

    def test_windows_moves_cursor(self):
        a, dev = self._adapter("windows")
        a.hover(10.6, 20.4)
        dev.mouse_move.assert_called_once_with((10, 20))
        dev.move.assert_not_called()  # device.move relocates the window, not the cursor

    def test_android_is_noop(self):
        a, dev = self._adapter("android")
        a.hover(10, 20)
        dev.mouse_move.assert_not_called()


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

    def test_screenshot_retries_transient_none_then_succeeds(
        self, fake_airtest, monkeypatch
    ):
        # snapshot() can momentarily return None (adb hiccup / minicap restart);
        # the adapter retries instead of feeding None into cv2_2_pil.
        import time

        monkeypatch.setattr(time, "sleep", lambda s: None)
        dev = _fake_device()
        dev.snapshot.side_effect = [None, None, "<bgr-ndarray>"]
        a = self._adapter(dev)
        data = a.screenshot()
        assert isinstance(data, bytes) and len(data) > 0
        assert dev.snapshot.call_count == 3

    def test_screenshot_recovers_from_snapshot_exception(
        self, fake_airtest, monkeypatch
    ):
        # A raised capture error is also transient — retry, don't propagate.
        import time

        monkeypatch.setattr(time, "sleep", lambda s: None)
        dev = _fake_device()
        dev.snapshot.side_effect = [RuntimeError("adb broke"), "<bgr-ndarray>"]
        a = self._adapter(dev)
        data = a.screenshot()
        assert isinstance(data, bytes) and len(data) > 0

    def test_screenshot_empty_frame_raises_qirabot_error(
        self, fake_airtest, monkeypatch
    ):
        # Persistent capture failure surfaces a clear QirabotError, not OpenCV's
        # raw !_src.empty() C++ assertion.
        import time

        from qirabot.exceptions import QirabotError

        monkeypatch.setattr(time, "sleep", lambda s: None)
        dev = _fake_device()
        dev.snapshot.return_value = None
        a = self._adapter(dev)
        with pytest.raises(QirabotError) as exc:
            a.screenshot()
        assert exc.value.code == "airtest.snapshot_empty"
        assert dev.snapshot.call_count == 3

    def test_screenshot_treats_zero_size_ndarray_as_empty(
        self, fake_airtest, monkeypatch
    ):
        # An empty ndarray (size == 0) trips the same assertion as None inside
        # cv2_2_pil, so it must be treated as a failed capture too.
        import time
        import types

        from qirabot.exceptions import QirabotError

        monkeypatch.setattr(time, "sleep", lambda s: None)
        dev = _fake_device()
        dev.snapshot.return_value = types.SimpleNamespace(size=0)
        a = self._adapter(dev)
        with pytest.raises(QirabotError) as exc:
            a.screenshot()
        assert exc.value.code == "airtest.snapshot_empty"

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
        a.execute("save_note", {"content": "x"})
        assert sleeps == []

    def test_hover_settles(self, fake_airtest, monkeypatch):
        # hover reveals delayed UI (tooltip/submenu), so it must settle before the
        # next screenshot — it is NOT a _NO_SETTLE action. (Settle is independent
        # of platform; the cursor move itself only happens on Windows.)
        import time

        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        a = self._adapter(_fake_device())
        a.execute("hover", {"x": 1, "y": 2})
        assert sleeps == [a._SETTLE_SECONDS]


class TestBind:
    def _bound(self, bot):
        from qirabot.bound import _BoundQirabot

        return _BoundQirabot(bot, "T")

    def test_click_injects_target(self):
        bot = MagicMock()
        bot.click.return_value = "T"
        self._bound(bot).click("Login", retry=2)
        bot.click.assert_called_once_with(
            "T", "Login", modifier="", timeout=0.0, interval=2.0, wait="", retry=2, model_alias="", language=""
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

        from qirabot.bound import _BoundQirabot
        from qirabot.client import Qirabot

        # Compare the call contract only: name, kind (positional vs
        # keyword-only) and default. Annotations are deliberately excluded —
        # under ``from __future__ import annotations`` they are raw source
        # strings, so an equivalent spelling (e.g. ``Callable[[StepResult]...``
        # vs ``Callable[["StepResult"]...``) would false-fail without changing
        # how the method is called.
        def call_contract(params):
            return [(p.name, p.kind, p.default) for p in params]

        for name in dir(Qirabot):
            if name.startswith("_") or name == "bind":
                continue  # bind() takes a target but creates the proxy, not proxied
            attr = inspect.getattr_static(Qirabot, name)
            if not inspect.isfunction(attr):
                continue
            params = list(inspect.signature(attr).parameters.values())
            if not (len(params) >= 2 and params[1].name == "target"):
                continue
            assert hasattr(_BoundQirabot, name), f"facade missing proxy for {name}"

            # The proxy must mirror the source signature exactly, minus the
            # injected ``target``. A plain hasattr check misses param drift —
            # e.g. adding a kwarg to Qirabot.click but forgetting the wrapper.
            bound_params = list(
                inspect.signature(getattr(_BoundQirabot, name)).parameters.values()
            )
            expected = call_contract(params[2:])  # drop self + target
            actual = call_contract(bound_params[1:])  # drop self
            assert actual == expected, (
                f"_BoundQirabot.{name} signature drifted from Qirabot.{name}:\n"
                f"  expected (minus target): {expected}\n"
                f"  actual:                  {actual}"
            )
