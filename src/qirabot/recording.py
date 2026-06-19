"""Cross-platform ffmpeg full-screen recorder (best-effort).

Records the whole screen to ``report_dir/recording.mp4`` so the HTML report
embeds it automatically. ffmpeg is a system binary (not a pip dependency), so it
is located with :func:`shutil.which` rather than imported; when it is missing,
the platform is unsupported, or the OS denies screen-capture permission, the
recorder only warns and degrades — it never raises into the running task.

Per platform the screen input differs:

* macOS  → ``-f avfoundation`` (needs the "Screen Recording" permission granted
  to the terminal/IDE running the script, else it records a black screen)
* Windows → ``-f gdigrab``
* Linux  → ``-f x11grab`` (needs an X display; Wayland without XWayland can't be
  captured this way)

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


def _find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


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


def _build_input_args(
    plat: str,
    fps: int,
    capture_cursor: bool,
    *,
    screen_index: str = _DEFAULT_SCREEN_INDEX,
) -> list[str] | None:
    """Build the ffmpeg screen-capture input args for ``plat``.

    Returns the args between ``ffmpeg -y`` and the output codec args, or
    ``None`` when the platform isn't supported. Pure (no subprocess / env reads
    beyond ``DISPLAY``) so it's unit-testable; ``screen_index`` is resolved by
    the caller for macOS.
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
        args += ["-i", "desktop"]
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

    def __init__(self, output: str, *, fps: int = 12, capture_cursor: bool = True):
        self.output = output
        self.fps = fps
        self.capture_cursor = capture_cursor
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
            logger.warning("recording skipped: ffmpeg not found (install it, e.g. `brew install ffmpeg`)")
            return False

        index = _detect_screen_index(ffmpeg) if sys.platform == "darwin" else _DEFAULT_SCREEN_INDEX
        input_args = _build_input_args(
            sys.platform, self.fps, self.capture_cursor, screen_index=index
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
            self.output,
        ]

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

        logger.info("recording started (%dfps) -> %s", self.fps, self.output)
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


def record(report_dir: str, *, filename: str = "recording.mp4", fps: int = 12) -> ScreenRecorder:
    """Convenience factory: a :class:`ScreenRecorder` writing ``report_dir/filename``.

    ``with record(bot.report_dir): ...`` records the full screen for the block.
    """
    return ScreenRecorder(os.path.join(report_dir, filename), fps=fps)
