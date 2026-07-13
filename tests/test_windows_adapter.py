"""Tests for the built-in Windows window backend.

Runs on any OS: the Win32 layer is exercised through the _user32/_gdi32 shims
and the send_inputs seam, asserting on the real INPUT ctypes structs
(SendInput sequences, flags, virtual-desktop normalization math).
"""

from __future__ import annotations

import pytest

import qirabot.windows as win
from qirabot.adapters.windows_adapter import (
    KEY_HOLD,
    SCANCODES,
    WindowsAdapter,
    char_scancode,
)
from qirabot.exceptions import QirabotError
from qirabot.windows import Window


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class FakeUser32:
    """Just enough user32 for Window resolution + geometry + foreground."""

    def __init__(self, windows=None, foreground=0):
        self.windows = windows or []  # [(hwnd, title, visible)]
        self.foreground = foreground

    def EnumWindows(self, proc, lparam):
        for hwnd, _title, _visible in self.windows:
            proc(hwnd, lparam)
        return 1

    def IsWindowVisible(self, hwnd):
        h = hwnd if isinstance(hwnd, int) else (hwnd or 0)
        return any(w[0] == h and w[2] for w in self.windows)

    def _title(self, hwnd):
        h = hwnd if isinstance(hwnd, int) else (hwnd or 0)
        for wh, title, _ in self.windows:
            if wh == h:
                return title
        return ""

    def GetWindowTextLengthW(self, hwnd):
        return len(self._title(hwnd))

    def GetWindowTextW(self, hwnd, buf, n):
        buf.value = self._title(hwnd)[: n - 1]
        return len(buf.value)

    def GetForegroundWindow(self):
        return self.foreground

    def SetForegroundWindow(self, hwnd):
        return 1

    def ShowWindow(self, hwnd, cmd):
        return 1

    def SetThreadDpiAwarenessContext(self, ctx):
        return 1  # pretend there was a previous context


@pytest.fixture
def fake_env(monkeypatch):
    """Fake user32 + captured send_inputs + fixed geometry.

    Window client area: 800x600 at screen (100, 50); virtual desktop:
    2560x1440 with a NEGATIVE origin (-1280, 0) — a monitor left of primary.
    """
    user32 = FakeUser32(windows=[(42, "Genshin Impact", True)], foreground=42)
    monkeypatch.setattr(win, "_user32", lambda: user32)
    monkeypatch.setattr(win, "_gdi32", lambda: object())

    sent: list[win.INPUT] = []
    monkeypatch.setattr(win, "send_inputs", lambda evs: sent.extend(evs))
    monkeypatch.setattr(
        win, "client_rect", lambda hwnd: (100, 50, 800, 600)
    )
    monkeypatch.setattr(win, "virtual_screen", lambda: (-1280, 0, 2560, 1440))

    sleeps: list[float] = []
    monkeypatch.setattr(
        "qirabot.adapters.windows_adapter.time.sleep", lambda s: sleeps.append(s)
    )
    return {"user32": user32, "sent": sent, "sleeps": sleeps}


def key_events(sent):
    return [e for e in sent if e.type == win.INPUT_KEYBOARD]


def mouse_events(sent):
    return [e for e in sent if e.type == win.INPUT_MOUSE]


# ---------------------------------------------------------------------------
# Window resolution
# ---------------------------------------------------------------------------


class TestWindow:
    def test_requires_hwnd_or_title(self):
        with pytest.raises(QirabotError) as ei:
            Window()
        assert ei.value.code == "windows.window_unspecified"
        assert "pyautogui" in str(ei.value)  # points at the full-desktop path

    def test_title_regex_resolves_unique_match(self, monkeypatch):
        user32 = FakeUser32(
            windows=[(1, "Notepad", True), (2, "Genshin Impact", True), (3, "hidden", False)]
        )
        monkeypatch.setattr(win, "_user32", lambda: user32)
        assert Window(title_re="Genshin").hwnd == 2

    def test_no_match_lists_visible_titles(self, monkeypatch):
        user32 = FakeUser32(windows=[(1, "Notepad", True)])
        monkeypatch.setattr(win, "_user32", lambda: user32)
        with pytest.raises(QirabotError) as ei:
            _ = Window(title_re="Genshin").hwnd
        assert ei.value.code == "windows.window_not_found"
        assert "Notepad" in str(ei.value)

    def test_ambiguous_match_lists_candidates(self, monkeypatch):
        user32 = FakeUser32(windows=[(1, "Chrome - a", True), (2, "Chrome - b", True)])
        monkeypatch.setattr(win, "_user32", lambda: user32)
        with pytest.raises(QirabotError) as ei:
            _ = Window(title_re="Chrome").hwnd
        assert ei.value.code == "windows.window_ambiguous"
        assert "hwnd=1" in str(ei.value)

    def test_explicit_hwnd_skips_enumeration(self):
        assert Window(hwnd=1234).hwnd == 1234

    def test_accepts_only_window(self, fake_env):
        assert WindowsAdapter.accepts(Window(hwnd=42))
        assert not WindowsAdapter.accepts(object())


# ---------------------------------------------------------------------------
# Coordinate normalization
# ---------------------------------------------------------------------------


class TestCoordinates:
    def test_virtual_desktop_normalization_with_negative_origin(self, fake_env):
        adapter = WindowsAdapter(Window(hwnd=42))
        adapter.hover(0, 0)  # client (0,0) = screen (100, 50)
        ev = mouse_events(fake_env["sent"])[0]
        # screen (100,50) - origin (-1280,0) = (1380, 50) over (2559, 1439)
        assert ev.mi.dx == round(1380 * 65535 / 2559)
        assert ev.mi.dy == round(50 * 65535 / 1439)
        assert ev.mi.dwFlags == (
            win.MOUSEEVENTF_MOVE | win.MOUSEEVENTF_ABSOLUTE | win.MOUSEEVENTF_VIRTUALDESK
        )

    def test_device_info_reports_client_pixels(self, fake_env):
        info = WindowsAdapter(Window(hwnd=42)).device_info()
        assert (info.platform, info.width, info.height) == ("desktop", 800, 600)

    def test_window_info_for_recorder(self, fake_env):
        assert WindowsAdapter(Window(hwnd=42)).window_info() == {
            "title": "Genshin Impact",
            "hwnd": 42,
        }


# ---------------------------------------------------------------------------
# Mouse
# ---------------------------------------------------------------------------


class TestMouse:
    def test_click_hardening_sequence(self, fake_env):
        WindowsAdapter(Window(hwnd=42)).click(400, 300)
        sent = fake_env["sent"]
        flags = [e.mi.dwFlags for e in mouse_events(sent)]
        move = win.MOUSEEVENTF_MOVE | win.MOUSEEVENTF_ABSOLUTE | win.MOUSEEVENTF_VIRTUALDESK
        # 3 approach moves (jitter, jitter, target), press, release
        assert flags == [move, move, move, win.MOUSEEVENTF_LEFTDOWN, win.MOUSEEVENTF_LEFTUP]
        # the press is held for CLICK_DURATION
        assert 0.1 in fake_env["sleeps"]

    def test_right_click_uses_right_button(self, fake_env):
        WindowsAdapter(Window(hwnd=42)).right_click(1, 1)
        flags = [e.mi.dwFlags for e in mouse_events(fake_env["sent"])]
        assert win.MOUSEEVENTF_RIGHTDOWN in flags and win.MOUSEEVENTF_RIGHTUP in flags

    def test_mouse_down_up_tracks_held_state(self, fake_env):
        adapter = WindowsAdapter(Window(hwnd=42))
        adapter.mouse_down(10, 10)
        assert adapter._mouse_held
        adapter.mouse_up(20, 20)
        assert not adapter._mouse_held
        flags = [e.mi.dwFlags for e in mouse_events(fake_env["sent"])]
        assert win.MOUSEEVENTF_LEFTDOWN in flags and win.MOUSEEVENTF_LEFTUP in flags

    def test_click_reasserts_held_modifiers_before_press(self, fake_env):
        # A modifier held via key_down can be lost before the click lands
        # (key_down's ensure_foreground failed, or ensure_foreground's ALT-tap
        # unlock released it). The click must re-press held keys after its own
        # ensure_foreground, BEFORE the button goes down.
        adapter = WindowsAdapter(Window(hwnd=42))
        adapter.key_down("alt")
        del fake_env["sent"][:]
        adapter.click(10, 10)
        sent = fake_env["sent"]
        keys = key_events(sent)
        assert [(e.ki.wScan, bool(e.ki.dwFlags & win.KEYEVENTF_KEYUP)) for e in keys] == [
            (SCANCODES["LALT"][0], False),
        ]
        first_down = next(
            i for i, e in enumerate(sent)
            if e.type == win.INPUT_MOUSE and e.mi.dwFlags == win.MOUSEEVENTF_LEFTDOWN
        )
        assert sent.index(keys[0]) < first_down
        # paced so frame-polling apps sample the modifier before the button
        assert KEY_HOLD in fake_env["sleeps"]

    def test_click_without_held_keys_injects_no_key_events(self, fake_env):
        WindowsAdapter(Window(hwnd=42)).click(10, 10)
        assert key_events(fake_env["sent"]) == []

    def test_modifier_click_dispatch_full_sequence(self, fake_env):
        # execute("click", modifier=...) end to end: alt down (key_down), alt
        # re-assert, button press/release, alt up — with the release AFTER the
        # button comes back up.
        adapter = WindowsAdapter(Window(hwnd=42))
        adapter._dispatch("click", {"x": 10, "y": 20, "modifier": "alt"})
        sent = fake_env["sent"]
        alt = SCANCODES["LALT"][0]
        keys = [(e.ki.wScan, bool(e.ki.dwFlags & win.KEYEVENTF_KEYUP)) for e in key_events(sent)]
        assert keys == [(alt, False), (alt, False), (alt, True)]
        last_up = max(
            i for i, e in enumerate(sent)
            if e.type == win.INPUT_MOUSE and e.mi.dwFlags == win.MOUSEEVENTF_LEFTUP
        )
        alt_release = next(
            i for i, e in enumerate(sent)
            if e.type == win.INPUT_KEYBOARD and e.ki.dwFlags & win.KEYEVENTF_KEYUP
        )
        assert last_up < alt_release
        # game-tuned pacing: a long lead before the click (games animate into
        # their modifier mode) and a tail after the button release
        assert WindowsAdapter._MODIFIER_LEAD in fake_env["sleeps"]
        assert WindowsAdapter._MODIFIER_TAIL in fake_env["sleeps"]
        assert WindowsAdapter._MODIFIER_LEAD >= 0.3

    def test_mouse_down_reasserts_held_modifiers(self, fake_env):
        adapter = WindowsAdapter(Window(hwnd=42))
        adapter.key_down("shift")
        del fake_env["sent"][:]
        adapter.mouse_down(10, 10)
        keys = key_events(fake_env["sent"])
        assert [(e.ki.wScan, bool(e.ki.dwFlags & win.KEYEVENTF_KEYUP)) for e in keys] == [
            (SCANCODES["LSHIFT"][0], False),
        ]

    def test_release_all_inputs_sweeps(self, fake_env):
        adapter = WindowsAdapter(Window(hwnd=42))
        adapter.key_down("shift")
        adapter.mouse_down(1, 1)
        del fake_env["sent"][:]
        adapter.release_all_inputs()
        sent = fake_env["sent"]
        ups = [e for e in key_events(sent) if e.ki.dwFlags & win.KEYEVENTF_KEYUP]
        assert len(ups) == 1 and ups[0].ki.wScan == SCANCODES["LSHIFT"][0]
        assert mouse_events(sent)[-1].mi.dwFlags == win.MOUSEEVENTF_LEFTUP
        assert not adapter._held_keys and not adapter._mouse_held


# ---------------------------------------------------------------------------
# Wheel
# ---------------------------------------------------------------------------


class TestWheel:
    def test_vertical_wheel_notches(self, fake_env):
        adapter = WindowsAdapter(Window(hwnd=42))
        adapter._scroll_action("scroll", {"direction": "down", "amount": 500})
        wheel = [e for e in mouse_events(fake_env["sent"]) if e.mi.dwFlags == win.MOUSEEVENTF_WHEEL]
        assert len(wheel) == 1
        # 500px -> 5 notches down -> -600 (stored as unsigned 32-bit)
        assert wheel[0].mi.mouseData == (-600) & 0xFFFFFFFF

    def test_horizontal_wheel(self, fake_env):
        adapter = WindowsAdapter(Window(hwnd=42))
        adapter._scroll_action("scroll", {"direction": "right", "amount": 100})
        hwheel = [e for e in mouse_events(fake_env["sent"]) if e.mi.dwFlags == win.MOUSEEVENTF_HWHEEL]
        assert len(hwheel) == 1
        assert hwheel[0].mi.mouseData == 120

    def test_scroll_at_moves_to_anchor_first(self, fake_env):
        adapter = WindowsAdapter(Window(hwnd=42))
        adapter._scroll_action("scroll_at", {"direction": "up", "amount": 100, "x": 10, "y": 20})
        evs = mouse_events(fake_env["sent"])
        assert evs[0].mi.dwFlags & win.MOUSEEVENTF_MOVE  # anchor move
        assert evs[-1].mi.dwFlags == win.MOUSEEVENTF_WHEEL
        assert evs[-1].mi.mouseData == 120  # up = positive


# ---------------------------------------------------------------------------
# Keyboard
# ---------------------------------------------------------------------------


class TestKeyboard:
    def test_single_key_scancode_tap_with_hold(self, fake_env):
        WindowsAdapter(Window(hwnd=42)).press_key("Enter")
        evs = key_events(fake_env["sent"])
        assert [(e.ki.wScan, bool(e.ki.dwFlags & win.KEYEVENTF_KEYUP)) for e in evs] == [
            (0x1C, False), (0x1C, True),
        ]
        assert all(e.ki.dwFlags & win.KEYEVENTF_SCANCODE for e in evs)
        assert KEY_HOLD in fake_env["sleeps"]

    def test_combo_holds_mods_and_releases_in_reverse(self, fake_env):
        WindowsAdapter(Window(hwnd=42)).press_key("ctrl+shift+a")
        evs = key_events(fake_env["sent"])
        seq = [(e.ki.wScan, bool(e.ki.dwFlags & win.KEYEVENTF_KEYUP)) for e in evs]
        ctrl, shift, a = SCANCODES["LCTRL"][0], SCANCODES["LSHIFT"][0], SCANCODES["A"][0]
        assert seq == [
            (ctrl, False), (shift, False),  # mods down in order
            (a, False), (a, True),          # base tap
            (shift, True), (ctrl, True),    # mods up in reverse
        ]

    def test_extended_key_sets_extended_flag(self, fake_env):
        WindowsAdapter(Window(hwnd=42)).press_key("ArrowUp")
        ev = key_events(fake_env["sent"])[0]
        assert ev.ki.wScan == 0x48
        assert ev.ki.dwFlags & win.KEYEVENTF_EXTENDEDKEY

    def test_unmapped_char_falls_back_to_unicode(self, fake_env):
        WindowsAdapter(Window(hwnd=42)).press_key("é")
        evs = key_events(fake_env["sent"])
        assert all(e.ki.dwFlags & win.KEYEVENTF_UNICODE for e in evs)
        assert evs[0].ki.wScan == ord("é")

    def test_unmappable_named_key_raises(self, fake_env):
        with pytest.raises(NotImplementedError):
            WindowsAdapter(Window(hwnd=42)).press_key("VolumeMute")

    def test_key_down_warns_when_foreground_fails(self, fake_env, monkeypatch, caplog):
        # Keyboard input follows focus: if the window can't be fronted the
        # press lands elsewhere, so the failure must at least be surfaced.
        monkeypatch.setattr(win, "ensure_foreground", lambda hwnd: False)
        adapter = WindowsAdapter(Window(hwnd=42))
        with caplog.at_level("WARNING", logger="qirabot"):
            adapter.key_down("alt")
        assert any("foreground" in r.message for r in caplog.records)
        # the key is still injected (best effort) and tracked for release
        assert adapter._held_keys == [SCANCODES["LALT"]]

    def test_key_down_before_side_effect_invariant(self, fake_env):
        # key_down on an unmappable key must raise BEFORE injecting anything
        # (the _press_key_held/_click_with_modifiers degrade contract).
        adapter = WindowsAdapter(Window(hwnd=42))
        with pytest.raises(NotImplementedError):
            adapter.key_down("VolumeMute")
        assert key_events(fake_env["sent"]) == []


class TestTypeText:
    def test_ascii_goes_scancode_with_shift_wrap(self, fake_env):
        WindowsAdapter(Window(hwnd=42)).type_focused("Hi!")
        evs = key_events(fake_env["sent"])
        seq = [(e.ki.wScan, bool(e.ki.dwFlags & win.KEYEVENTF_KEYUP)) for e in evs]
        shift, h, i, one = (
            SCANCODES["LSHIFT"][0], SCANCODES["H"][0], SCANCODES["I"][0], SCANCODES["1"][0],
        )
        assert seq == [
            (shift, False), (h, False), (h, True), (shift, True),  # H
            (i, False), (i, True),                                  # i
            (shift, False), (one, False), (one, True), (shift, True),  # !
        ]
        assert all(e.ki.dwFlags & win.KEYEVENTF_SCANCODE for e in evs)

    def test_non_ascii_switches_whole_string_to_unicode(self, fake_env):
        WindowsAdapter(Window(hwnd=42)).type_focused("a你")
        evs = key_events(fake_env["sent"])
        # ALL events are unicode (no scancode/unicode mixing => ordering holds)
        assert all(e.ki.dwFlags & win.KEYEVENTF_UNICODE for e in evs)
        assert [e.ki.wScan for e in evs] == [ord("a"), ord("a"), ord("你"), ord("你")]

    def test_surrogate_pair_emoji(self, fake_env):
        WindowsAdapter(Window(hwnd=42)).type_focused("🎮")
        evs = key_events(fake_env["sent"])
        units = "🎮".encode("utf-16-le")
        expected = [int.from_bytes(units[i : i + 2], "little") for i in (0, 2)]
        assert [e.ki.wScan for e in evs] == expected * 2  # down pair + up pair

    def test_type_text_clicks_then_settles(self, fake_env):
        WindowsAdapter(Window(hwnd=42)).type_text(5, 5, "a")
        assert 0.3 in fake_env["sleeps"]  # FOCUS_SETTLE between click and keys


class TestCharScancode:
    @pytest.mark.parametrize(
        "ch,expected",
        [
            ("a", (False, "A")),
            ("Z", (True, "Z")),
            ("7", (False, "7")),
            (" ", (False, "SPACE")),
            ("!", (True, "1")),
            ("|", (True, "BACKSLASH")),
            ("你", None),
            ("\n", None),
        ],
    )
    def test_mapping(self, ch, expected):
        assert char_scancode(ch) == expected

    def test_every_scancode_name_resolvable(self):
        # every name the char tables can emit must exist in SCANCODES
        from qirabot.adapters.windows_adapter import SHIFT_CHARS, SYMBOL_CHARS

        for name in set(SHIFT_CHARS.values()) | set(SYMBOL_CHARS.values()):
            assert name in SCANCODES, name


# ---------------------------------------------------------------------------
# Foreground
# ---------------------------------------------------------------------------


class TestForeground:
    def test_input_skips_raise_when_already_foreground(self, fake_env, monkeypatch):
        calls = []
        monkeypatch.setattr(
            win, "ensure_foreground", lambda hwnd: calls.append(hwnd) or True
        )
        WindowsAdapter(Window(hwnd=42)).click(1, 1)
        assert calls == [42]

    def test_hwnd_representation_mismatch_is_still_foreground(self, monkeypatch):
        # 64-bit Windows sign-extends 32-bit HWNDs, so the same handle arrives
        # as a negative int (default c_int restype on GetForegroundWindow) and
        # as a sign-extended unsigned (int(c_void_p) in the EnumWindows
        # callback). A naive == treats the window as never-foreground and
        # fires the ALT-tap unlock on EVERY action — which releases a modifier
        # held around a click.
        raw = 0x80001234
        negative = raw - (1 << 32)            # GetForegroundWindow's view
        sign_extended = (1 << 64) + negative  # Window.hwnd's view
        user32 = FakeUser32(foreground=negative)
        monkeypatch.setattr(win, "_user32", lambda: user32)
        sent = []
        monkeypatch.setattr(win, "send_inputs", lambda evs: sent.extend(evs))

        assert win.ensure_foreground(sign_extended) is True
        assert sent == []  # already foreground: no ALT tap injected

    def test_ensure_foreground_alt_unlock_retry(self, monkeypatch):
        # Not foreground, SetForegroundWindow initially refused: the ALT tap
        # unlock must be injected, then the retry succeeds.
        class StubUser32(FakeUser32):
            def __init__(self):
                super().__init__()
                self.fg = 7
                self.set_calls = 0

            def GetForegroundWindow(self):
                return self.fg

            def SetForegroundWindow(self, hwnd):
                self.set_calls += 1
                if self.set_calls >= 2:
                    self.fg = 42
                return 1

        user32 = StubUser32()
        monkeypatch.setattr(win, "_user32", lambda: user32)
        sent = []
        monkeypatch.setattr(win, "send_inputs", lambda evs: sent.extend(evs))
        monkeypatch.setattr("qirabot.windows.time.sleep", lambda s: None)

        assert win.ensure_foreground(42) is True
        assert user32.set_calls == 2
        # the unlock was a no-op ALT tap (scancode 0x38 down+up)
        assert [e.ki.wScan for e in sent] == [0x38, 0x38]
