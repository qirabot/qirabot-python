"""Tests for the ffmpeg screen recorder and its client integration."""

import qirabot.client as client_mod
from qirabot import recording
from qirabot.client import Qirabot
from qirabot.recording import ScreenRecorder, _build_input_args, _detect_screen_index


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

    def __init__(self, output, *, fps=12, capture_cursor=True):
        self.output = output
        self.fps = fps
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
