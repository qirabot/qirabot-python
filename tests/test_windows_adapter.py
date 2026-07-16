"""Tests for the built-in Windows window backend.

Runs on any OS: the Win32 layer is exercised through the _user32/_gdi32 shims
and the send_inputs seam, asserting on the real INPUT ctypes structs
(SendInput sequences, flags, virtual-desktop normalization math).
"""

from __future__ import annotations

import ctypes

import pytest

import qirabot.windows as win
from qirabot.adapters.windows_adapter import (
    KEY_HOLD,
    PASTE_SETTLE,
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

    def __init__(self, windows=None, foreground=0, rects=None, classes=None):
        self.windows = windows or []  # [(hwnd, title, visible)]
        self.foreground = foreground
        self.rects = rects or {}  # hwnd -> (left, top, right, bottom)
        self.classes = classes or {}  # hwnd -> window class name
        self.messages = []  # SendMessageW calls: (hwnd, msg, wparam, lparam)

    def GetClassNameW(self, hwnd, buf, n):
        h = hwnd if isinstance(hwnd, int) else (hwnd or 0)
        buf.value = self.classes.get(h, "")[: n - 1]
        return len(buf.value)

    def LoadKeyboardLayoutW(self, layout, flags):
        return 0x04090409  # en-US HKL

    def SendMessageW(self, hwnd, msg, wparam, lparam):
        h = hwnd.value if hasattr(hwnd, "value") else hwnd
        self.messages.append((h, msg, wparam, lparam))
        return 0

    def GetWindowRect(self, hwnd, rect_ref):
        h = hwnd.value if hasattr(hwnd, "value") else hwnd
        if h not in self.rects:
            return 0
        rect = rect_ref._obj
        rect.left, rect.top, rect.right, rect.bottom = self.rects[h]
        return 1

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

    class FakeImm32:
        def ImmGetDefaultIMEWnd(self, hwnd):
            return 999  # the window's default IME window

    monkeypatch.setattr(win, "_imm32", lambda: FakeImm32())

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

    # In-memory clipboard so the paste fallback runs anywhere.
    clipboard = {"text": None, "sets": []}

    def _set_clipboard(text):
        clipboard["sets"].append(text)
        clipboard["text"] = text

    monkeypatch.setattr(win, "get_clipboard_text", lambda: clipboard["text"])
    monkeypatch.setattr(win, "set_clipboard_text", _set_clipboard)
    return {"user32": user32, "sent": sent, "sleeps": sleeps, "clipboard": clipboard}


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
        assert "ambiguous='largest'" in str(ei.value)  # points at the fix

    def test_title_is_literal_substring(self, monkeypatch):
        # Regex metacharacters in the title must not be interpreted: as a
        # regex, "Cloud(Beta)" would match "CloudBeta" (capture group), not
        # the literal text — the exact trap cloud-gaming titles hit.
        user32 = FakeUser32(windows=[(7, "MyGame · Cloud(Beta)", True)])
        monkeypatch.setattr(win, "_user32", lambda: user32)
        assert Window(title="Cloud(Beta)").hwnd == 7
        with pytest.raises(QirabotError) as ei:
            _ = Window(title_re="Cloud(Beta)").hwnd  # regex semantics: no match
        assert ei.value.code == "windows.window_not_found"

    def test_ambiguous_largest_picks_biggest_window(self, monkeypatch):
        # Three identically-titled windows (cloud client + overlays): the
        # game's main window is the biggest one.
        user32 = FakeUser32(
            windows=[
                (1, "MyGame · Cloud(Beta)", True),
                (2, "MyGame · Cloud(Beta)", True),
                (3, "MyGame · Cloud(Beta)", True),
            ],
            rects={1: (0, 0, 300, 200), 2: (0, 0, 1920, 1080), 3: (0, 0, 800, 600)},
        )
        monkeypatch.setattr(win, "_user32", lambda: user32)
        assert Window(title="MyGame", ambiguous="largest").hwnd == 2

    def test_ambiguous_largest_treats_rect_failure_as_zero_area(self, monkeypatch):
        user32 = FakeUser32(
            windows=[(1, "Genshin", True), (2, "Genshin", True)],
            rects={2: (0, 0, 100, 100)},  # GetWindowRect fails for hwnd=1
        )
        monkeypatch.setattr(win, "_user32", lambda: user32)
        assert Window(title="Genshin", ambiguous="largest").hwnd == 2

    def test_ambiguous_largest_with_unique_match_is_direct(self, monkeypatch):
        user32 = FakeUser32(windows=[(5, "Genshin", True)])  # no rects needed
        monkeypatch.setattr(win, "_user32", lambda: user32)
        assert Window(title="Genshin", ambiguous="largest").hwnd == 5

    def test_class_name_matches_untitled_window(self, monkeypatch):
        # A game's renderer window may not have set its title yet — class
        # matching must still find it (title matching never can).
        user32 = FakeUser32(
            windows=[(7, "", True), (8, "File Explorer", True)],
            classes={7: "UnityWndClass", 8: "CabinetWClass"},
        )
        monkeypatch.setattr(win, "_user32", lambda: user32)
        assert Window(class_name="UnityWndClass").hwnd == 7

    def test_class_name_combined_with_title(self, monkeypatch):
        user32 = FakeUser32(
            windows=[(1, "Game A", True), (2, "Game B", True)],
            classes={1: "UnityWndClass", 2: "UnityWndClass"},
        )
        monkeypatch.setattr(win, "_user32", lambda: user32)
        assert Window(class_name="UnityWndClass", title="Game B").hwnd == 2

    def test_timeout_polls_until_window_appears(self, monkeypatch):
        # Simulates binding to a game that is still starting: the window
        # only exists from the third enumeration onwards.
        user32 = FakeUser32(classes={7: "UnityWndClass"})
        real_enum, calls = user32.EnumWindows, {"n": 0}

        def enum_windows(proc, lparam):
            calls["n"] += 1
            if calls["n"] >= 3:
                user32.windows = [(7, "Game", True)]
            return real_enum(proc, lparam)

        user32.EnumWindows = enum_windows
        monkeypatch.setattr(win, "_user32", lambda: user32)
        sleeps: list[float] = []
        monkeypatch.setattr(win.time, "sleep", lambda s: sleeps.append(s))
        assert Window(class_name="UnityWndClass", timeout=60).hwnd == 7
        assert len(sleeps) == 2  # two misses, then found

    def test_timeout_zero_enumerates_once(self, monkeypatch):
        user32 = FakeUser32(windows=[(1, "Notepad", True)])
        calls = {"n": 0}
        real_enum = user32.EnumWindows

        def enum_windows(proc, lparam):
            calls["n"] += 1
            return real_enum(proc, lparam)

        user32.EnumWindows = enum_windows
        monkeypatch.setattr(win, "_user32", lambda: user32)
        with pytest.raises(QirabotError) as ei:
            _ = Window(class_name="UnityWndClass").hwnd
        assert ei.value.code == "windows.window_not_found"
        # one class enumeration + one title listing for the error message
        assert calls["n"] == 2

    def test_title_and_title_re_conflict(self):
        with pytest.raises(QirabotError) as ei:
            Window(title="a", title_re="b")
        assert ei.value.code == "windows.window_unspecified"

    def test_invalid_ambiguous_value(self):
        with pytest.raises(QirabotError) as ei:
            Window(title="a", ambiguous="biggest")
        assert ei.value.code == "windows.bad_argument"

    def test_explicit_hwnd_skips_enumeration(self):
        assert Window(hwnd=1234).hwnd == 1234

    def test_accepts_only_window(self, fake_env):
        assert WindowsAdapter.accepts(Window(hwnd=42))
        assert not WindowsAdapter.accepts(object())


# ---------------------------------------------------------------------------
# English IME
# ---------------------------------------------------------------------------


class TestEnglishIme:
    def test_first_input_forces_english_ime_once(self, fake_env):
        adapter = WindowsAdapter(Window(hwnd=42))
        adapter.press_key("esc")
        msgs = fake_env["user32"].messages
        lang = [m for m in msgs if m[1] == win.WM_INPUTLANGCHANGEREQUEST]
        assert [m[0] for m in lang] == [42]  # layout switch sent to the window
        ime = [m for m in msgs if m[1] == 0x0283]  # WM_IME_CONTROL
        assert [(m[0], m[2]) for m in ime] == [(999, 0x0006)]  # IMC_SETOPENSTATUS off
        adapter.press_key("esc")  # second input: no re-switch
        assert len([m for m in msgs if m[1] == win.WM_INPUTLANGCHANGEREQUEST]) == 1

    def test_english_ime_opt_out(self, fake_env):
        adapter = WindowsAdapter(Window(hwnd=42, english_ime=False))
        adapter.press_key("esc")
        assert fake_env["user32"].messages == []

    def test_pointer_action_also_prepares_ime(self, fake_env):
        adapter = WindowsAdapter(Window(hwnd=42))
        adapter.click(10, 10)
        msgs = fake_env["user32"].messages
        assert any(m[1] == win.WM_INPUTLANGCHANGEREQUEST for m in msgs)


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

    def test_modifier_click_dispatch_single_down(self, fake_env):
        # execute("click", modifier=...) end to end with the window already
        # foreground: EXACTLY one alt down, button press/release, alt up.
        # No duplicate down — games that toggle their modifier mode on every
        # down (Raw Input has no repeat flag) would switch the mode back off.
        adapter = WindowsAdapter(Window(hwnd=42))
        adapter._dispatch("click", {"x": 10, "y": 20, "modifier": "alt"})
        sent = fake_env["sent"]
        alt = SCANCODES["LALT"][0]
        keys = [(e.ki.wScan, bool(e.ki.dwFlags & win.KEYEVENTF_KEYUP)) for e in key_events(sent)]
        assert keys == [(alt, False), (alt, True)]
        last_up = max(
            i for i, e in enumerate(sent)
            if e.type == win.INPUT_MOUSE and e.mi.dwFlags == win.MOUSEEVENTF_LEFTUP
        )
        alt_release = next(
            i for i, e in enumerate(sent)
            if e.type == win.INPUT_KEYBOARD and e.ki.dwFlags & win.KEYEVENTF_KEYUP
        )
        assert last_up < alt_release  # released only after the button came up
        # game-tuned pacing: a long lead before the click (games animate into
        # their modifier mode) and a tail after the button release
        assert WindowsAdapter._MODIFIER_LEAD in fake_env["sleeps"]
        assert WindowsAdapter._MODIFIER_TAIL in fake_env["sleeps"]
        assert WindowsAdapter._MODIFIER_LEAD >= 0.3

    def test_click_without_held_keys_injects_no_key_events(self, fake_env):
        WindowsAdapter(Window(hwnd=42)).click(10, 10)
        assert key_events(fake_env["sent"]) == []

    def test_click_reasserts_when_key_down_was_undelivered(self, fake_env):
        # key_down fired while another window had focus: the down went there.
        # Once the target IS foreground, the next click must re-press the held
        # key before the button goes down.
        user32 = fake_env["user32"]
        adapter = WindowsAdapter(Window(hwnd=42))
        user32.foreground = 7  # someone else owns the foreground
        adapter.key_down("alt")
        assert adapter._held_undelivered
        user32.foreground = 42  # target window regains the foreground
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
        assert not adapter._held_undelivered  # repaired
        # a second click does NOT re-press again (single-repair, no flapping)
        del fake_env["sent"][:]
        adapter.click(10, 10)
        assert key_events(fake_env["sent"]) == []

    def test_click_reasserts_after_foreground_recovery(self, fake_env):
        # Window not foreground at click time: ensure_foreground runs (its
        # ALT-tap unlock may have released a held ALT), so held keys must be
        # re-pressed before the button goes down.
        user32 = fake_env["user32"]
        adapter = WindowsAdapter(Window(hwnd=42))
        adapter.key_down("shift")
        user32.foreground = 7  # focus stolen after key_down
        del fake_env["sent"][:]
        adapter.click(10, 10)
        keys = key_events(fake_env["sent"])
        # last key event is the shift re-press (ensure_foreground may emit its
        # own ALT tap before it while the fake refuses to front the window)
        assert (keys[-1].ki.wScan, bool(keys[-1].ki.dwFlags & win.KEYEVENTF_KEYUP)) == (
            SCANCODES["LSHIFT"][0], False,
        )
        assert KEY_HOLD in fake_env["sleeps"]

    def test_key_up_clears_undelivered_flag(self, fake_env):
        user32 = fake_env["user32"]
        adapter = WindowsAdapter(Window(hwnd=42))
        user32.foreground = 7
        adapter.key_down("alt")
        assert adapter._held_undelivered
        adapter.key_up("alt")
        assert not adapter._held_undelivered  # nothing held, nothing to repair

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
        # 500px -> 5 notches down, one WHEEL_DELTA event each (games count
        # events, not summed deltas; stored as unsigned 32-bit)
        assert len(wheel) == 5
        assert all(e.mi.mouseData == (-120) & 0xFFFFFFFF for e in wheel)

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

    def test_non_ascii_switches_whole_string_to_paste(self, fake_env):
        # Unicode injection (VK_PACKET) needs a TranslateMessage loop games
        # don't run — unmappable text must arrive as clipboard + Ctrl+V, with
        # the WHOLE string pasted (no scancode/paste mixing => ordering holds).
        WindowsAdapter(Window(hwnd=42)).type_focused("a你")
        assert fake_env["clipboard"]["sets"][0] == "a你"
        evs = key_events(fake_env["sent"])
        seq = [(e.ki.wScan, bool(e.ki.dwFlags & win.KEYEVENTF_KEYUP)) for e in evs]
        ctrl, v = SCANCODES["LCTRL"][0], SCANCODES["V"][0]
        # exactly one ctrl down (toggle-mode games treat a duplicate as "off")
        assert seq == [(ctrl, False), (v, False), (v, True), (ctrl, True)]
        assert all(e.ki.dwFlags & win.KEYEVENTF_SCANCODE for e in evs)
        # the clipboard isn't restored under the target mid-paste
        assert PASTE_SETTLE in fake_env["sleeps"]

    def test_paste_restores_previous_clipboard(self, fake_env):
        fake_env["clipboard"]["text"] = "user data"
        WindowsAdapter(Window(hwnd=42)).type_focused("你好")
        assert fake_env["clipboard"]["sets"] == ["你好", "user data"]
        assert fake_env["clipboard"]["text"] == "user data"

    def test_paste_skips_restore_when_clipboard_was_empty(self, fake_env):
        WindowsAdapter(Window(hwnd=42)).type_focused("你")
        assert fake_env["clipboard"]["sets"] == ["你"]

    def test_paste_restore_failure_is_swallowed(self, fake_env, monkeypatch, caplog):
        # A flaky restore (clipboard held by another process) must not turn a
        # successful paste into a typing failure.
        fake_env["clipboard"]["text"] = "user data"
        calls = []

        def _flaky_set(text):
            calls.append(text)
            if len(calls) > 1:
                raise QirabotError("busy", code="windows.clipboard_busy")

        monkeypatch.setattr(win, "set_clipboard_text", _flaky_set)
        with caplog.at_level("WARNING", logger="qirabot"):
            WindowsAdapter(Window(hwnd=42)).type_focused("你")
        assert calls == ["你", "user data"]
        assert any("clipboard" in r.message for r in caplog.records)

    def test_env_knob_reverts_to_unicode_injection(self, fake_env, monkeypatch):
        # Targets that block pasting: QIRA_TEXT_FALLBACK=unicode restores the
        # KEYEVENTF_UNICODE path, now with a hold between down and up.
        monkeypatch.setenv("QIRA_TEXT_FALLBACK", "unicode")
        WindowsAdapter(Window(hwnd=42)).type_focused("a你")
        assert fake_env["clipboard"]["sets"] == []
        evs = key_events(fake_env["sent"])
        assert all(e.ki.dwFlags & win.KEYEVENTF_UNICODE for e in evs)
        assert [e.ki.wScan for e in evs] == [ord("a"), ord("a"), ord("你"), ord("你")]
        assert KEY_HOLD in fake_env["sleeps"]

    def test_surrogate_pair_emoji_unicode_path(self, fake_env, monkeypatch):
        monkeypatch.setenv("QIRA_TEXT_FALLBACK", "unicode")
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
# Clipboard (Win32 layer)
# ---------------------------------------------------------------------------


class FakeClipboardUser32:
    """user32 clipboard surface; handles are addresses of real ctypes memory."""

    def __init__(self):
        self.data_handle = 0  # what GetClipboardData returns
        self.open_ok = True
        self.emptied = False
        self.set_handle = None
        self.closed = 0

    def OpenClipboard(self, owner):
        return 1 if self.open_ok else 0

    def CloseClipboard(self):
        self.closed += 1
        return 1

    def GetClipboardData(self, fmt):
        return self.data_handle

    def EmptyClipboard(self):
        self.emptied = True
        return 1

    def SetClipboardData(self, fmt, handle):
        self.set_handle = handle.value if hasattr(handle, "value") else handle
        return self.set_handle


class FakeKernel32:
    def __init__(self):
        self.buffers = {}  # addr -> buffer (kept alive for wstring_at)
        self.freed = []

    def GlobalAlloc(self, flags, size):
        buf = ctypes.create_string_buffer(int(size))
        addr = ctypes.addressof(buf)
        self.buffers[addr] = buf
        return addr

    def GlobalLock(self, handle):
        return handle.value if hasattr(handle, "value") else handle

    def GlobalUnlock(self, handle):
        return 1

    def GlobalFree(self, handle):
        self.freed.append(handle.value if hasattr(handle, "value") else handle)


class TestClipboard:
    @pytest.fixture
    def clip_env(self, monkeypatch):
        user32, kernel32 = FakeClipboardUser32(), FakeKernel32()
        monkeypatch.setattr(win, "_user32", lambda: user32)
        monkeypatch.setattr(win, "_kernel32", lambda: kernel32)
        monkeypatch.setattr("qirabot.windows.time.sleep", lambda s: None)
        return user32, kernel32

    def test_set_writes_nul_terminated_utf16(self, clip_env):
        user32, kernel32 = clip_env
        win.set_clipboard_text("你好a")
        assert user32.emptied
        # Compare raw bytes: CF_UNICODETEXT is UTF-16 regardless of the test
        # host's wchar_t width, so wstring_at would misread this off-Windows.
        raw = kernel32.buffers[user32.set_handle].raw
        assert raw == "你好a".encode("utf-16-le") + b"\x00\x00"
        assert user32.closed == 1
        assert kernel32.freed == []  # ownership transferred to the system

    def test_get_reads_unicode_text(self, clip_env):
        user32, _ = clip_env
        buf = ctypes.create_unicode_buffer("剪贴板")
        user32.data_handle = ctypes.addressof(buf)
        assert win.get_clipboard_text() == "剪贴板"
        assert user32.closed == 1

    def test_get_returns_none_for_non_text(self, clip_env):
        user32, _ = clip_env
        assert win.get_clipboard_text() is None
        assert user32.closed == 1  # clipboard not left open

    def test_get_returns_none_when_clipboard_busy(self, clip_env):
        user32, _ = clip_env
        user32.open_ok = False
        assert win.get_clipboard_text() is None

    def test_set_raises_and_frees_when_clipboard_busy(self, clip_env):
        user32, kernel32 = clip_env
        user32.open_ok = False
        with pytest.raises(QirabotError) as ei:
            win.set_clipboard_text("x")
        assert ei.value.code == "windows.clipboard_busy"
        assert len(kernel32.freed) == 1  # our copy was not leaked


# ---------------------------------------------------------------------------
# Foreground
# ---------------------------------------------------------------------------


class TestForeground:
    def test_click_skips_ensure_foreground_when_already_foreground(
        self, fake_env, monkeypatch
    ):
        # Already foreground: no ensure_foreground call at all — its ALT-tap
        # unlock must never get a chance to fire mid modifier-click.
        calls = []
        monkeypatch.setattr(
            win, "ensure_foreground", lambda hwnd: calls.append(hwnd) or True
        )
        WindowsAdapter(Window(hwnd=42)).click(1, 1)
        assert calls == []

    def test_click_fronts_window_when_not_foreground(self, fake_env, monkeypatch):
        calls = []
        monkeypatch.setattr(
            win, "ensure_foreground", lambda hwnd: calls.append(hwnd) or True
        )
        fake_env["user32"].foreground = 7
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
