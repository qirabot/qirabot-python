"""Tests for the ffmpeg screen recorder and its client integration."""

from pathlib import Path

import qirabot.client as client_mod
from qirabot import recording
from qirabot import report as report_mod
from qirabot.client import Qirabot
from qirabot.recording import (
    ScreenRecorder,
    _build_input_args,
    _detect_audio_device,
    _detect_screen_index,
)

# Minimal step log entry so write_html / report() has something to render.
_LOG_ENTRY = {
    "section": "setup", "action_type": "click", "params": {}, "output": "",
    "finished": False, "success": True, "coords": None, "screenshot": "", "thumb": "",
}


# --------------------------------------------------------------------------- #
# _build_input_args (per-platform, pure)
# --------------------------------------------------------------------------- #
class TestBuildInputArgs:
    def test_macos(self):
        args = _build_input_args("darwin", 12, True, screen_index="1")
        assert args is not None
        assert args[:2] == ["-f", "avfoundation"]
        assert "-capture_cursor" in args and args[args.index("-capture_cursor") + 1] == "1"
        assert args[-2:] == ["-i", "1:none"]
        assert "-framerate" in args and args[args.index("-framerate") + 1] == "12"

    def test_macos_no_cursor(self):
        args = _build_input_args("darwin", 12, False, screen_index="2")
        assert args is not None
        assert args[args.index("-capture_cursor") + 1] == "0"
        assert args[-1] == "2:none"

    def test_windows(self):
        args = _build_input_args("win32", 30, True)
        assert args is not None
        assert args[:2] == ["-f", "gdigrab"]
        assert args[-2:] == ["-i", "desktop"]
        assert "-draw_mouse" not in args  # cursor on by default, no flag needed

    def test_windows_no_cursor(self):
        args = _build_input_args("win32", 30, False)
        assert args is not None
        assert args[args.index("-draw_mouse") + 1] == "0"

    def test_windows_window_by_title(self):
        args = _build_input_args("win32", 30, True, window="Notepad")
        assert args is not None
        assert args[-2:] == ["-i", "title=Notepad"]

    def test_windows_window_by_handle(self):
        # A numeric window string is treated as an hwnd= handle.
        args = _build_input_args("win32", 30, True, window="13579")
        assert args is not None
        assert args[-2:] == ["-i", "hwnd=13579"]

    def test_windows_system_audio_second_input(self):
        args = _build_input_args(
            "win32", 30, True, audio_device="virtual-audio-capturer", audio_offset=-0.4
        )
        assert args is not None
        # Video input first (desktop), then a dshow audio input.
        assert "desktop" in args
        assert "dshow" in args
        assert "audio=virtual-audio-capturer" in args
        assert "-rtbufsize" in args
        assert args[args.index("-itsoffset") + 1] == "-0.4"

    def test_windows_no_audio_no_dshow(self):
        args = _build_input_args("win32", 30, True)
        assert args is not None
        assert "dshow" not in args  # silent unless an audio device is given

    def test_non_windows_ignores_window_and_audio(self):
        # window/audio are Windows-only; other platforms keep full-screen silent.
        args = _build_input_args("linux", 15, True, window="X", audio_device="Y")
        assert args is not None
        assert "dshow" not in args and "title=X" not in args

    def test_linux_uses_display_env(self, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":5")
        args = _build_input_args("linux", 15, True)
        assert args is not None
        assert args[:2] == ["-f", "x11grab"]
        assert args[-2:] == ["-i", ":5"]

    def test_linux_default_display(self, monkeypatch):
        monkeypatch.delenv("DISPLAY", raising=False)
        args = _build_input_args("linux", 15, True)
        assert args is not None
        assert args[-1] == ":0.0"

    def test_unsupported_platform(self):
        assert _build_input_args("sunos5", 12, True) is None


# --------------------------------------------------------------------------- #
# _detect_screen_index (macOS avfoundation probe)
# --------------------------------------------------------------------------- #
class _FakeCompleted:
    def __init__(self, stderr):
        self.stderr = stderr


class TestDetectScreenIndex:
    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("QIRA_SCREEN_INDEX", "7")
        assert _detect_screen_index("ffmpeg") == "7"

    def test_parses_capture_screen_line(self, monkeypatch):
        monkeypatch.delenv("QIRA_SCREEN_INDEX", raising=False)
        stderr = (
            "[AVFoundation] AVFoundation video devices:\n"
            "[AVFoundation] [0] FaceTime HD Camera\n"
            "[AVFoundation] [3] Capture screen 0\n"
        )
        monkeypatch.setattr(recording.subprocess, "run", lambda *a, **k: _FakeCompleted(stderr))
        assert _detect_screen_index("ffmpeg") == "3"

    def test_falls_back_on_error(self, monkeypatch):
        monkeypatch.delenv("QIRA_SCREEN_INDEX", raising=False)

        def boom(*a, **k):
            raise OSError("no ffmpeg")

        monkeypatch.setattr(recording.subprocess, "run", boom)
        assert _detect_screen_index("ffmpeg") == "1"


# --------------------------------------------------------------------------- #
# _detect_audio_device (Windows dshow system-audio probe)
# --------------------------------------------------------------------------- #
class TestDetectAudioDevice:
    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("QIRA_AUDIO_DEVICE", "CABLE Output")
        assert _detect_audio_device("ffmpeg") == "CABLE Output"

    def test_prefers_virtual_audio_capturer(self, monkeypatch):
        monkeypatch.delenv("QIRA_AUDIO_DEVICE", raising=False)
        stderr = (
            '[dshow] "Microphone (Realtek Audio)" (audio)\n'
            '[dshow] "Stereo Mix (Realtek Audio)" (audio)\n'
            '[dshow] "virtual-audio-capturer" (audio)\n'
        )
        monkeypatch.setattr(recording.subprocess, "run", lambda *a, **k: _FakeCompleted(stderr))
        assert _detect_audio_device("ffmpeg") == "virtual-audio-capturer"

    def test_falls_back_to_stereo_mix(self, monkeypatch):
        monkeypatch.delenv("QIRA_AUDIO_DEVICE", raising=False)
        stderr = (
            '[dshow] "Microphone (Realtek Audio)" (audio)\n'
            '[dshow] "Stereo Mix (Realtek Audio)" (audio)\n'
        )
        monkeypatch.setattr(recording.subprocess, "run", lambda *a, **k: _FakeCompleted(stderr))
        assert _detect_audio_device("ffmpeg") == "Stereo Mix (Realtek Audio)"

    def test_none_when_no_match(self, monkeypatch):
        monkeypatch.delenv("QIRA_AUDIO_DEVICE", raising=False)
        stderr = '[dshow] "Microphone (Realtek Audio)" (audio)\n'
        monkeypatch.setattr(recording.subprocess, "run", lambda *a, **k: _FakeCompleted(stderr))
        assert _detect_audio_device("ffmpeg") is None

    def test_none_on_error(self, monkeypatch):
        monkeypatch.delenv("QIRA_AUDIO_DEVICE", raising=False)

        def boom(*a, **k):
            raise OSError("no ffmpeg")

        monkeypatch.setattr(recording.subprocess, "run", boom)
        assert _detect_audio_device("ffmpeg") is None


# --------------------------------------------------------------------------- #
# ScreenRecorder.start / stop
# --------------------------------------------------------------------------- #
class _FakeStdin:
    def __init__(self):
        self.data = b""
        self.closed = False

    def write(self, b):
        self.data += b

    def flush(self):
        pass

    def close(self):
        self.closed = True


class _FakeProc:
    def __init__(self):
        self.stdin = _FakeStdin()
        self._poll = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self._poll

    def wait(self, timeout=None):
        self._poll = 0
        return 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class TestScreenRecorder:
    def test_start_degrades_without_ffmpeg(self, monkeypatch, tmp_path):
        monkeypatch.setattr(recording.shutil, "which", lambda _: None)
        rec = ScreenRecorder(str(tmp_path / "recording.mp4"))
        assert rec.start() is False  # warns, never raises
        assert rec.active is False

    def test_start_builds_ffmpeg_command(self, monkeypatch, tmp_path):
        captured = {}

        class _FakePopen:
            def __init__(self, cmd, **kw):
                captured["cmd"] = cmd
                captured["kw"] = kw
                self.stdin = _FakeStdin()

            def poll(self):
                return None

        monkeypatch.setattr(recording.sys, "platform", "darwin")
        monkeypatch.setattr(recording, "_find_ffmpeg", lambda: "ffmpeg")
        monkeypatch.setattr(recording, "_detect_screen_index", lambda f: "1")
        monkeypatch.setattr(recording.subprocess, "Popen", _FakePopen)

        out = str(tmp_path / "recording.mp4")
        rec = ScreenRecorder(out, fps=20)
        assert rec.start() is True
        assert rec.active is True

        cmd = captured["cmd"]
        assert cmd[0] == "ffmpeg" and cmd[1] == "-y"
        assert cmd[-1] == out
        for token in ("-f", "avfoundation", "libx264", "ultrafast", "yuv420p"):
            assert token in cmd
        assert captured["kw"]["stdin"] is recording.subprocess.PIPE

    def test_start_windows_window_and_audio_command(self, monkeypatch, tmp_path):
        captured = {}

        class _FakePopen:
            def __init__(self, cmd, **kw):
                captured["cmd"] = cmd
                self.stdin = _FakeStdin()

            def poll(self):
                return None

        monkeypatch.setattr(recording.sys, "platform", "win32")
        monkeypatch.setattr(recording, "_find_ffmpeg", lambda: "ffmpeg")
        monkeypatch.setattr(recording, "_detect_audio_device", lambda f: "virtual-audio-capturer")
        monkeypatch.setattr(recording.subprocess, "Popen", _FakePopen)

        out = str(tmp_path / "recording.mp4")
        rec = ScreenRecorder(out, fps=15, window="Notepad", audio=True)
        assert rec.start() is True

        cmd = captured["cmd"]
        assert "title=Notepad" in cmd               # per-window video input
        assert "audio=virtual-audio-capturer" in cmd  # system-audio input
        assert cmd[cmd.index("-c:a") + 1] == "aac"  # audio gets encoded
        assert cmd[-1] == out

    def test_start_windows_audio_missing_device_is_silent(self, monkeypatch, tmp_path):
        captured = {}

        class _FakePopen:
            def __init__(self, cmd, **kw):
                captured["cmd"] = cmd
                self.stdin = _FakeStdin()

            def poll(self):
                return None

        monkeypatch.setattr(recording.sys, "platform", "win32")
        monkeypatch.setattr(recording, "_find_ffmpeg", lambda: "ffmpeg")
        monkeypatch.setattr(recording, "_detect_audio_device", lambda f: None)  # none found
        monkeypatch.setattr(recording.subprocess, "Popen", _FakePopen)

        rec = ScreenRecorder(str(tmp_path / "recording.mp4"), audio=True)
        assert rec.start() is True  # degrades to silent, never fails
        cmd = captured["cmd"]
        assert "-c:a" not in cmd and "dshow" not in cmd

    def test_stop_sends_q_and_returns_path(self, monkeypatch, tmp_path):
        out = tmp_path / "recording.mp4"
        out.write_bytes(b"fake-mp4-bytes")  # non-empty -> treated as valid
        rec = ScreenRecorder(str(out))
        proc = _FakeProc()
        rec._proc = proc

        assert rec.stop() == str(out)
        assert proc.stdin.data == b"q\n"  # graceful quit signal sent
        assert proc.stdin.closed is True

    def test_stop_without_proc_is_noop(self, tmp_path):
        rec = ScreenRecorder(str(tmp_path / "recording.mp4"))
        assert rec.stop() is None

    def test_stop_no_file_returns_none(self, tmp_path):
        rec = ScreenRecorder(str(tmp_path / "missing.mp4"))
        rec._proc = _FakeProc()
        assert rec.stop() is None  # nothing was written


# --------------------------------------------------------------------------- #
# Client integration
# --------------------------------------------------------------------------- #
class _FakeRecorder:
    """Drop-in for ScreenRecorder that records lifecycle without spawning ffmpeg."""

    instances: list["_FakeRecorder"] = []

    def __init__(self, output, *, fps=12, capture_cursor=True, window=None, audio=False, audio_offset=None):
        self.output = output
        self.fps = fps
        self.window = window
        self.audio = audio
        self.audio_offset = audio_offset
        self.started = False
        self.stopped = False
        self._active = False
        _FakeRecorder.instances.append(self)

    def start(self):
        self.started = True
        self._active = True
        return True

    @property
    def active(self):
        return self._active

    def stop(self, timeout=10.0):
        self.stopped = True
        self._active = False
        return self.output


class TestClientRecordingWiring:
    def _use_fake(self, monkeypatch):
        _FakeRecorder.instances = []
        monkeypatch.setattr(client_mod, "ScreenRecorder", _FakeRecorder)

    def test_record_true_autostarts(self, monkeypatch, tmp_path):
        self._use_fake(monkeypatch)
        Qirabot(api_key="k", task_id="t", record=True, report_dir=str(tmp_path))
        assert len(_FakeRecorder.instances) == 1
        rec = _FakeRecorder.instances[0]
        assert rec.started is True
        assert rec.output.endswith("recording.mp4")

    def test_record_false_does_not_record(self, monkeypatch, tmp_path):
        self._use_fake(monkeypatch)
        bot = Qirabot(api_key="k", task_id="t", report_dir=str(tmp_path))
        assert _FakeRecorder.instances == []
        assert bot._recorder is None

    def test_env_var_enables_recording(self, monkeypatch, tmp_path):
        self._use_fake(monkeypatch)
        monkeypatch.setenv("QIRA_RECORD", "1")
        Qirabot(api_key="k", task_id="t", report_dir=str(tmp_path))
        assert len(_FakeRecorder.instances) == 1

    def test_start_recording_is_idempotent(self, monkeypatch, tmp_path):
        self._use_fake(monkeypatch)
        bot = Qirabot(api_key="k", task_id="t", record=True, report_dir=str(tmp_path))
        assert bot.start_recording() is True  # already running -> no new ffmpeg
        assert len(_FakeRecorder.instances) == 1

    def test_stop_recording_clears_slot(self, monkeypatch, tmp_path):
        self._use_fake(monkeypatch)
        bot = Qirabot(api_key="k", task_id="t", record=True, report_dir=str(tmp_path))
        rec = _FakeRecorder.instances[0]
        assert bot.stop_recording() == rec.output
        assert rec.stopped is True
        assert bot._recorder is None
        # close() must not try to stop again (slot already cleared)
        bot.close()
        assert len(_FakeRecorder.instances) == 1

    def test_close_stops_before_report_written(self, monkeypatch, tmp_path):
        self._use_fake(monkeypatch)
        bot = Qirabot(api_key="k", task_id="t", record=True, report_dir=str(tmp_path))
        rec = _FakeRecorder.instances[0]

        order = {}

        def fake_write_report(out=None):
            order["stopped_when_report_written"] = rec.stopped
            return None

        monkeypatch.setattr(bot, "_write_report", fake_write_report)
        bot.close()
        assert order["stopped_when_report_written"] is True

    def test_manual_recording_without_flag(self, monkeypatch, tmp_path):
        self._use_fake(monkeypatch)
        bot = Qirabot(api_key="k", task_id="t", report_dir=str(tmp_path))
        assert bot.start_recording() is True
        assert len(_FakeRecorder.instances) == 1
        assert bot.stop_recording() == _FakeRecorder.instances[0].output

    def test_record_window_defers_until_target(self, monkeypatch, tmp_path):
        self._use_fake(monkeypatch)
        bot = Qirabot(
            api_key="k", task_id="t", record=True, record_window=True, report_dir=str(tmp_path)
        )
        # No target at construction time -> deferred, nothing started yet.
        assert _FakeRecorder.instances == []
        assert bot._recorder is None
        # First action resolves a window; the _get_adapter hook then starts it.
        monkeypatch.setattr(bot, "_resolve_window_target", lambda target: "My Window")
        bot._maybe_start_recording(target=object())
        assert len(_FakeRecorder.instances) == 1
        rec = _FakeRecorder.instances[0]
        assert rec.window == "My Window" and rec.started is True

    def test_record_window_degrades_to_fullscreen(self, monkeypatch, tmp_path):
        self._use_fake(monkeypatch)
        bot = Qirabot(
            api_key="k", task_id="t", record=True, record_window=True, report_dir=str(tmp_path)
        )
        monkeypatch.setattr(bot, "_resolve_window_target", lambda target: None)  # not resolvable
        bot._maybe_start_recording(target=object())
        assert len(_FakeRecorder.instances) == 1
        assert _FakeRecorder.instances[0].window is None  # full screen fallback

    def test_record_window_starts_only_once(self, monkeypatch, tmp_path):
        self._use_fake(monkeypatch)
        bot = Qirabot(
            api_key="k", task_id="t", record=True, record_window=True, report_dir=str(tmp_path)
        )
        monkeypatch.setattr(bot, "_resolve_window_target", lambda target: "W")
        bot._maybe_start_recording(target=object())
        bot._maybe_start_recording(target=object())  # later action -> no second ffmpeg
        assert len(_FakeRecorder.instances) == 1

    def test_record_audio_passed_to_recorder(self, monkeypatch, tmp_path):
        self._use_fake(monkeypatch)
        bot = Qirabot(
            api_key="k", task_id="t", record=True, record_audio=True, report_dir=str(tmp_path)
        )
        # record_window off -> starts immediately (full screen) with audio on.
        assert len(_FakeRecorder.instances) == 1
        assert _FakeRecorder.instances[0].audio is True


# --------------------------------------------------------------------------- #
# Recording-failure notice in the report
# --------------------------------------------------------------------------- #
class _FailingRecorder:
    """Recorder whose start() fails (e.g. ffmpeg missing)."""

    def __init__(self, output, *, fps=12, capture_cursor=True, window=None, audio=False, audio_offset=None):
        self.output = output

    def start(self):
        return False

    @property
    def active(self):
        return False

    def stop(self, timeout=10.0):
        return None


class TestReportRecordingNotice:
    def test_write_html_renders_notice(self, tmp_path):
        out = report_mod.write_html(
            [_LOG_ENTRY], tmp_path / "r.html", record_error="ffmpeg not found"
        )
        markup = out.read_text()
        assert "class='notice'" in markup
        assert "ffmpeg not found" in markup

    def test_write_html_video_wins_over_error(self, tmp_path):
        out = report_mod.write_html(
            [_LOG_ENTRY], tmp_path / "r.html",
            recording="recording.mp4", record_error="ignored",
        )
        markup = out.read_text()
        assert "<video" in markup
        assert "class='notice'" not in markup

    def test_client_notes_failed_recording(self, monkeypatch, tmp_path):
        monkeypatch.setattr(client_mod, "ScreenRecorder", _FailingRecorder)
        bot = Qirabot(api_key="k", task_id="t", record=True, report_dir=str(tmp_path))
        assert bot._recorder is None  # start() failed
        bot._log.append(dict(_LOG_ENTRY))
        out = bot.report(str(tmp_path / "report.html"))
        markup = Path(out).read_text()
        assert "Recording was requested but not produced" in markup
        assert "<video" not in markup

    def test_client_zero_byte_recording_is_failure(self, monkeypatch, tmp_path):
        monkeypatch.setattr(client_mod, "ScreenRecorder", _FailingRecorder)
        bot = Qirabot(api_key="k", task_id="t", record=True, report_dir=str(tmp_path))
        (Path(bot.report_dir) / "recording.mp4").write_bytes(b"")  # 0 bytes
        bot._log.append(dict(_LOG_ENTRY))
        out = bot.report(str(tmp_path / "report.html"))
        markup = Path(out).read_text()
        assert "Recording was requested but not produced" in markup
        assert "<video" not in markup

    def test_client_valid_recording_embeds_no_notice(self, monkeypatch, tmp_path):
        monkeypatch.setattr(client_mod, "ScreenRecorder", _FailingRecorder)
        bot = Qirabot(api_key="k", task_id="t", record=True, report_dir=str(tmp_path))
        (Path(bot.report_dir) / "recording.mp4").write_bytes(b"data")
        bot._log.append(dict(_LOG_ENTRY))
        out = bot.report(str(tmp_path / "report.html"))
        markup = Path(out).read_text()
        assert "<video" in markup
        assert "Recording was requested but not produced" not in markup

    def test_no_notice_when_record_not_requested(self, tmp_path):
        bot = Qirabot(api_key="k", task_id="t", report_dir=str(tmp_path))
        bot._log.append(dict(_LOG_ENTRY))
        out = bot.report(str(tmp_path / "report.html"))
        markup = Path(out).read_text()
        assert "Recording was requested but not produced" not in markup


# --------------------------------------------------------------------------- #
# Report survives Ctrl+C during shutdown
# --------------------------------------------------------------------------- #
class _InterruptingRecorder:
    """Recorder whose stop() raises KeyboardInterrupt — simulates a Ctrl+C
    landing while ffmpeg is being finalized in close()."""

    def __init__(self, output, *, fps=12, capture_cursor=True, window=None, audio=False, audio_offset=None):
        self.output = output

    def start(self):
        return True

    @property
    def active(self):
        return False

    def stop(self, timeout=10.0):
        raise KeyboardInterrupt()


class TestReportSurvivesCtrlC:
    def test_report_written_when_recording_stop_interrupted(self, monkeypatch, tmp_path):
        # A Ctrl+C during recording finalize must not skip the report.
        monkeypatch.setattr(client_mod, "ScreenRecorder", _InterruptingRecorder)
        bot = Qirabot(api_key="k", task_id="t", record=True, report_dir=str(tmp_path))
        bot._log.append(dict(_LOG_ENTRY))
        report_path = Path(bot.report_dir) / "report.html"

        bot.close()  # must not raise, and must still produce the report

        assert report_path.exists()

    def test_close_swallows_keyboardinterrupt_from_report_write(self, monkeypatch, tmp_path):
        # The fallback path (non-main-thread, where SIGINT suppression is a
        # no-op): a KeyboardInterrupt raised inside the write is swallowed so
        # close() finishes its teardown instead of aborting.
        bot = Qirabot(api_key="k", task_id="t", report_dir=str(tmp_path))
        bot._log.append(dict(_LOG_ENTRY))

        def boom(out=None):
            raise KeyboardInterrupt()

        monkeypatch.setattr(bot, "_write_report", boom)
        bot.close()  # does not raise
        assert bot._closed is True

    def test_suppress_sigint_ignores_then_restores(self):
        import signal

        original = signal.getsignal(signal.SIGINT)
        with client_mod._suppress_sigint():
            assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
        assert signal.getsignal(signal.SIGINT) is original
