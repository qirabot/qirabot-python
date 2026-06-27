"""Cross-platform ffmpeg full-screen recorder (best-effort).

Records the whole screen to ``report_dir/recording.mp4`` so the HTML report
embeds it automatically. ffmpeg is a system binary (not a pip dependency), so it
is located with :func:`shutil.which` rather than imported; when it is missing,
the platform is unsupported, or the OS denies screen-capture permission, the
recorder only warns and degrades — it never raises into the running task.

Per platform the screen input differs:

* macOS  → ``-f avfoundation`` (needs the "Screen Recording" permission granted
  to the terminal/IDE running the script, else it records a black screen)
* Windows → ``-f gdigrab`` (and, optionally, per-window capture via
  ``title=``/``hwnd=`` plus system audio via a DirectShow loopback device)
* Linux  → ``-f x11grab`` (needs an X display; Wayland without XWayland can't be
  captured this way)

On Windows the recorder can additionally capture a single window (``window=``)
and the system audio (``audio=``). Both are best-effort: a missing audio device
or an unmappable window degrades to full-screen / silent capture with a warning.
Note that ``gdigrab`` per-window capture yields black/frozen frames for a
minimized, occluded, or GPU-composited (game) window — keep the window visible,
or fall back to full-screen for games.

Typical usage is via the SDK (``Qirabot(record=True)`` or
``bot.start_recording()``), but it can be used standalone::

    from qirabot.recording import ScreenRecorder

    with ScreenRecorder("out.mp4"):
        ...  # do work; recording is finalized on exit
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from typing import IO

logger = logging.getLogger("qirabot")

# avfoundation screen index used when device probing fails (on this Mac
# ``Capture screen 0`` is index 1).
_DEFAULT_SCREEN_INDEX = "1"

# Preferred Windows DirectShow device names for capturing *system* (loopback)
# audio, in priority order. ffmpeg has no native WASAPI loopback on Windows, so
# system sound must come through a dshow source: a WASAPI-loopback virtual device
# (driver-free, from screen-capture-recorder) or the driver-dependent Stereo Mix.
_WIN_SYSTEM_AUDIO_HINTS = ("virtual-audio-capturer", "stereo mix", "立体声混音")


def _find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _detect_audio_device(ffmpeg: str) -> str | None:
    """Resolve a Windows DirectShow *system audio* device name (Windows only).

    ``ffmpeg -list_devices true -f dshow -i dummy`` writes lines like
    ``"virtual-audio-capturer" (audio)`` to stderr; we pick the first device
    whose name matches a known loopback/stereo-mix hint. ``QIRA_AUDIO_DEVICE``
    overrides the probe; probe failures (or no match) return ``None`` so the
    caller degrades to a silent recording.
    """
    override = os.environ.get("QIRA_AUDIO_DEVICE")
    if override:
        return override
    try:
        proc = subprocess.run(
            [ffmpeg, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # Device names are quoted; the audio block lists them as `"name" (audio)`.
    names = re.findall(r'"([^"]+)"', proc.stderr)
    lowered = [(n, n.lower()) for n in names]
    for hint in _WIN_SYSTEM_AUDIO_HINTS:
        for name, low in lowered:
            if hint in low:
                return name
    return None


def _detect_screen_index(ffmpeg: str) -> str:
    """Resolve the avfoundation screen device index (macOS only).

    ``ffmpeg -f avfoundation -list_devices true -i ""`` writes lines like
    ``[1] Capture screen 0`` to stderr; we take the ``[N]`` in front of the
    first "Capture screen" line. ``QIRA_SCREEN_INDEX`` overrides the probe;
    probe failures fall back to :data:`_DEFAULT_SCREEN_INDEX`.
    """
    override = os.environ.get("QIRA_SCREEN_INDEX")
    if override:
        return override
    try:
        proc = subprocess.run(
            [ffmpeg, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return _DEFAULT_SCREEN_INDEX
    for line in proc.stderr.splitlines():
        if "Capture screen" in line:
            m = re.search(r"\[(\d+)\]\s*Capture screen", line)
            if m:
                return m.group(1)
    return _DEFAULT_SCREEN_INDEX


def _win_video_target(window: str | None) -> str:
    """gdigrab input filename for ``window``.

    A numeric string is treated as a window handle (``hwnd=``, needs a recent
    ffmpeg); any other non-empty string is a window title (``title=``, widely
    supported). Empty/None records the whole desktop.
    """
    if not window:
        return "desktop"
    if window.isdigit():
        return f"hwnd={window}"
    return f"title={window}"


def _build_input_args(
    plat: str,
    fps: int,
    capture_cursor: bool,
    *,
    screen_index: str = _DEFAULT_SCREEN_INDEX,
    window: str | None = None,
    audio_device: str | None = None,
    audio_offset: float | None = None,
) -> list[str] | None:
    """Build the ffmpeg screen-capture input args for ``plat``.

    Returns the args between ``ffmpeg -y`` and the output codec args, or
    ``None`` when the platform isn't supported. Pure (no subprocess / env reads
    beyond ``DISPLAY``) so it's unit-testable; ``screen_index`` is resolved by
    the caller for macOS.

    ``window``/``audio_device`` are Windows-only for now (per-window capture and
    system-audio loopback); other platforms ignore them and keep full-screen,
    silent capture.
    """
    if plat == "darwin":
        return [
            "-f", "avfoundation",
            "-framerate", str(fps),
            "-capture_cursor", "1" if capture_cursor else "0",
            "-i", f"{screen_index}:none",  # video index + no audio
        ]
    if plat == "win32":
        args = ["-f", "gdigrab", "-framerate", str(fps)]
        if not capture_cursor:
            args += ["-draw_mouse", "0"]  # gdigrab draws the cursor by default
        args += ["-i", _win_video_target(window)]
        if audio_device:
            # Second input: system audio via DirectShow. rtbufsize/thread_queue
            # absorb loopback bursts; itsoffset (negative) compensates the
            # loopback delay so audio lines up with the video.
            if audio_offset is not None:
                args += ["-itsoffset", str(audio_offset)]
            args += [
                "-f", "dshow",
                "-thread_queue_size", "1024",
                "-rtbufsize", "100M",
                "-i", f"audio={audio_device}",
            ]
        return args
    if plat.startswith("linux"):
        display = os.environ.get("DISPLAY") or ":0.0"
        args = ["-f", "x11grab", "-framerate", str(fps)]
        if not capture_cursor:
            args += ["-draw_mouse", "0"]  # x11grab draws the cursor by default
        args += ["-i", display]
        return args
    return None


class ScreenRecorder:
    """Start/stop a single ffmpeg subprocess recording the full screen."""

    def __init__(
        self,
        output: str,
        *,
        fps: int = 12,
        capture_cursor: bool = True,
        window: str | None = None,
        audio: bool | str = False,
        audio_offset: float | None = None,
    ):
        self.output = output
        self.fps = fps
        self.capture_cursor = capture_cursor
        # Windows-only extras. ``window``: a window title (or numeric handle) to
        # capture instead of the whole desktop. ``audio``: True = auto-detect a
        # system-audio device, a str = explicit dshow device name, False = no
        # audio. ``audio_offset``: seconds (usually negative) to shift audio for
        # A/V sync. All degrade gracefully when unavailable.
        self.window = window
        self.audio = audio
        self.audio_offset = audio_offset
        self._proc: subprocess.Popen[bytes] | None = None
        self._log: IO[bytes] | None = None

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> bool:
        """Start recording; return True on success.

        Best-effort: missing ffmpeg / unsupported platform only warn and return
        False — they never raise.
        """
        if self._proc is not None:
            return self.active

        ffmpeg = _find_ffmpeg()
        if not ffmpeg:
            logger.warning("recording skipped: ffmpeg not found (install it and ensure it's on PATH: https://ffmpeg.org/download.html)")
            return False

        index = _detect_screen_index(ffmpeg) if sys.platform == "darwin" else _DEFAULT_SCREEN_INDEX

        # Resolve system-audio device (Windows only). True -> probe; str -> use
        # as-is. A requested-but-missing device degrades to a silent recording.
        audio_device: str | None = None
        if self.audio and sys.platform == "win32":
            audio_device = self.audio if isinstance(self.audio, str) else _detect_audio_device(ffmpeg)
            if not audio_device:
                logger.warning(
                    "recording: no system-audio device found (install screen-capture-recorder's "
                    "'virtual-audio-capturer' or enable 'Stereo Mix', or set QIRA_AUDIO_DEVICE); "
                    "recording without sound"
                )
        elif self.audio and sys.platform != "win32":
            logger.warning("recording: audio capture is currently Windows-only; recording without sound")

        input_args = _build_input_args(
            sys.platform, self.fps, self.capture_cursor,
            screen_index=index,
            window=self.window,
            audio_device=audio_device,
            audio_offset=self.audio_offset,
        )
        if input_args is None:
            logger.warning("recording skipped: platform %r not supported", sys.platform)
            return False

        os.makedirs(os.path.dirname(os.path.abspath(self.output)), exist_ok=True)
        log_path = os.path.join(os.path.dirname(self.output), "recording.ffmpeg.log")

        cmd = [
            ffmpeg, "-y",
            *input_args,
            "-vcodec", "libx264",
            "-preset", "ultrafast",   # minimize CPU stolen from the task being driven
            "-pix_fmt", "yuv420p",    # HTML5 / inline-playback compatible
        ]
        if audio_device:
            cmd += ["-c:a", "aac", "-b:a", "160k"]
        cmd.append(self.output)

        try:
            self._log = open(log_path, "wb")
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,    # used for graceful stop (write 'q')
                stdout=self._log,
                stderr=subprocess.STDOUT,
            )
        except OSError as e:
            logger.warning("recording failed to start: %s", e)
            self._cleanup_log()
            self._proc = None
            return False

        scope = f"window {self.window!r}" if self.window else "full screen"
        sound = f"audio={audio_device}" if audio_device else "no audio"
        logger.info("recording started (%dfps, %s, %s) -> %s", self.fps, scope, sound, self.output)
        return True

    def stop(self, timeout: float = 10.0) -> str | None:
        """Gracefully stop and flush to disk; return the output path or None."""
        proc = self._proc
        if proc is None:
            return None
        self._proc = None

        if proc.poll() is None:
            try:
                # Send 'q' so ffmpeg exits normally and writes the mp4 moov atom,
                # keeping the file seekable/playable.
                if proc.stdin:
                    proc.stdin.write(b"q\n")
                    proc.stdin.flush()
                    proc.stdin.close()
            except (OSError, ValueError):
                pass
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

        self._cleanup_log()

        if os.path.exists(self.output) and os.path.getsize(self.output) > 0:
            logger.info("recording saved: %s", self.output)
            return self.output
        log_path = os.path.join(os.path.dirname(self.output), "recording.ffmpeg.log")
        logger.warning("recording produced no valid file (see %s)", log_path)
        return None

    def _cleanup_log(self) -> None:
        if self._log is not None:
            try:
                self._log.close()
            except OSError:
                pass
            self._log = None

    def __enter__(self) -> ScreenRecorder:
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop()


def record(
    report_dir: str,
    *,
    filename: str = "recording.mp4",
    fps: int = 12,
    window: str | None = None,
    audio: bool | str = False,
    audio_offset: float | None = None,
) -> ScreenRecorder:
    """Convenience factory: a :class:`ScreenRecorder` writing ``report_dir/filename``.

    ``with record(bot.report_dir): ...`` records the full screen for the block.
    ``window`` (Windows: a window title/handle) records just that window and
    ``audio`` (Windows: True to auto-detect system audio, or a dshow device
    name) adds sound — both degrade to full-screen / silent elsewhere.
    """
    return ScreenRecorder(
        os.path.join(report_dir, filename),
        fps=fps,
        window=window,
        audio=audio,
        audio_offset=audio_offset,
    )
