"""Qirabot SDK client."""

from __future__ import annotations

import atexit
import contextlib
import io
import json
import logging
import os
import signal
import sys
import threading
import time
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator, Literal

from qirabot._heartbeat import Heartbeat
from qirabot._optional import require
from qirabot._tools import build_tool_defs
from qirabot._transport import Transport
from qirabot.recording import MjpegStreamRecorder, Recorder, ScreenRecorder, device_recorder
from qirabot.adapters import auto
from qirabot.adapters.base import DeviceAdapter, ScreenshotConfig
from qirabot.bound import _BoundQirabot
from qirabot.exceptions import (
    ActionError,
    AuthenticationError,
    QirabotError,
    QirabotTimeoutError,
    TaskTerminatedError,
    _is_retryable,
)

if TYPE_CHECKING:
    from playwright.sync_api import ViewportSize

logger = logging.getLogger("qirabot")


@contextlib.contextmanager
def _suppress_sigint() -> Iterator[None]:
    """Make the wrapped block uninterruptible by Ctrl+C (SIGINT).

    Used in :meth:`Qirabot.close` so a flurry of Ctrl+C during shutdown cannot
    skip writing the run report — a plain try/except can't guarantee this because
    Python delivers each SIGINT as a fresh ``KeyboardInterrupt`` at whatever
    bytecode boundary it lands on, including inside the report write itself.

    Only the SIGINTs that arrive *inside* the block are suppressed; the original
    KeyboardInterrupt that triggered shutdown keeps propagating once we return.
    A no-op (best-effort) off the main thread or where SIGINT can't be reassigned
    (``signal.signal`` is main-thread only) — callers keep their own try/except
    as the fallback for that case.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    try:
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (ValueError, OSError):
        yield
        return
    try:
        yield
    finally:
        try:
            signal.signal(signal.SIGINT, previous)
        except (ValueError, OSError):
            pass


@dataclass
class StepResult:
    """Result of a single step in bot.ai()."""

    step: int
    action_type: str
    params: dict[str, Any] = field(default_factory=dict)
    output: str = ""
    finished: bool = False
    decision: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    step_duration_ms: int = 0
    llm_decision_duration_ms: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any], step: int) -> StepResult:
        return cls(
            step=step,
            action_type=data.get("actionType", ""),
            params=data.get("params") or {},
            output=data.get("output", ""),
            finished=data.get("finished", False),
            decision=data.get("decision", ""),
            input_tokens=data.get("inputTokens", 0),
            output_tokens=data.get("outputTokens", 0),
            thinking_tokens=data.get("thinkingTokens", 0),
            step_duration_ms=data.get("stepDurationMs", 0),
            llm_decision_duration_ms=data.get("llmDecisionDurationMs", 0),
        )


@dataclass
class VerifyResult:
    """Result of bot.verify(). Truthy when the assertion holds.

    Use directly as a bool (``if bot.verify(...)`` / ``assert bot.verify(...)``);
    read ``reason`` for the model's explanation, e.g. when an assertion fails
    unexpectedly. ``output_tokens`` already includes ``thinking_tokens``
    (Anthropic semantics), so this call's spend is ``input_tokens +
    output_tokens`` — do not add thinking again.
    """

    passed: bool
    reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerifyResult:
        return cls(
            passed=data.get("finished", False),
            reason=data.get("output", ""),
            input_tokens=data.get("inputTokens", 0),
            output_tokens=data.get("outputTokens", 0),
            thinking_tokens=data.get("thinkingTokens", 0),
        )

    def __bool__(self) -> bool:
        return self.passed


class ExtractResult(str):
    """Text extracted by bot.extract(); usable directly as a str.

    Behaves as the extracted string for every str operation and additionally
    carries the extraction's token usage. ``output_tokens`` already includes
    ``thinking_tokens`` (Anthropic semantics): this call's spend is
    ``input_tokens + output_tokens``. Note: str operations that build a new
    string (slicing, concatenation, ``.strip()``) return a plain str and drop
    these attributes — read tokens on the value returned by extract() itself.
    """

    input_tokens: int
    output_tokens: int
    thinking_tokens: int

    def __new__(
        cls,
        text: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        thinking_tokens: int = 0,
    ) -> ExtractResult:
        obj = super().__new__(cls, text)
        obj.input_tokens = input_tokens
        obj.output_tokens = output_tokens
        obj.thinking_tokens = thinking_tokens
        return obj

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExtractResult:
        return cls(
            data.get("output", ""),
            input_tokens=data.get("inputTokens", 0),
            output_tokens=data.get("outputTokens", 0),
            thinking_tokens=data.get("thinkingTokens", 0),
        )


# How a bot.ai() run ended. "max_steps" matches the server's task-level
# max_steps event name; the server itself records the command as plain
# "failed", so this is the SDK's finer-grained local view.
RunStatus = Literal["completed", "goal_failed", "max_steps", "error"]


@dataclass
class RunResult:
    """Result of bot.ai() multi-step operation.

    ``success`` is the pass/fail verdict (True only when the model declared the
    goal achieved); ``status`` says *how* the run ended:

    - ``"completed"``: model declared done and the goal was achieved
    - ``"goal_failed"``: model concluded the goal is unreachable (login wall,
      captcha, frozen app)
    - ``"max_steps"``: step budget ran out before the model finished — a
      truncation, not a capability verdict; consider raising ``max_steps``
    - ``"error"``: the server reported a terminal error

    ``success`` is True iff ``status == "completed"``.
    """

    success: bool
    output: str = ""
    steps: list[StepResult] = field(default_factory=list)
    status: RunStatus = "completed"


class Qirabot:
    """AI automation bolt-on for any framework.

    Usage::

        bot = Qirabot("qk_xxx")
        bot.click(page, "Login button")
        bot.type_text(page, "Username field", "admin@example.com")
        result = bot.ai(page, "Find the cheapest item and add to cart")
        bot.close()
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        timeout: float = 120.0,
        verify_ssl: bool = True,
        model_alias: str = "",
        language: str = "",
        task_name: str = "",
        task_id: str = "",
        source: str = "sdk",
        report: bool = True,
        report_dir: str = "",
        screenshot_format: str = "jpeg",
        screenshot_quality: int = 80,
        screenshot_annotate: bool = True,
        retry: int = 1,
        retry_delay: float = 1.0,
        settle_seconds: float | None = None,
        record: bool = False,
        record_fps: int = 12,
        record_window: bool = False,
        record_audio: bool | str = False,
        record_audio_offset: float | None = None,
        record_mjpeg_url: str | None = None,
        record_device: bool = False,
        heartbeat: bool = True,
    ):
        api_key = api_key or os.environ.get("QIRA_API_KEY", "")
        # Fail fast on a missing key: it's a local config error, so surface an
        # actionable message here instead of letting an empty key reach the
        # server and bounce back as an opaque 401 after a wasted round-trip.
        if not api_key:
            raise AuthenticationError(
                "No API key provided. Set the QIRA_API_KEY environment variable "
                "or pass api_key=... to Qirabot().",
                code="auth.api_key_missing",
            )
        base_url = base_url or os.environ.get("QIRA_BASE_URL", "https://app.qirabot.com")
        self._transport = Transport(base_url=base_url, api_key=api_key, timeout=timeout, verify_ssl=verify_ssl)
        self._adapters: dict[int, DeviceAdapter] = {}
        self._pw_instances: list[Any] = []
        self._cdp_pages: list[Any] = []
        self._model_alias = model_alias
        self._language = language
        self._task_name = task_name
        self._external_task = bool(task_id)
        self._closed = False
        # Set once a terminal status has been reported to the server (success via
        # close() or failure via fail()), so close()'s default success-complete
        # never overrides an already-reported failure.
        self._terminalized = False
        if task_id:
            self._task_id: str | None = task_id
        else:
            create_body: dict[str, Any] = {"name": self._task_name}
            if source:
                create_body["source"] = source
            if model_alias:
                create_body["modelAlias"] = model_alias
            result = self._transport.post("/tasks/create", json_data=create_body)
            self._task_id = result["taskId"]
        # Background liveness signal: without it the server's orphan cleaner
        # times the task out after ~5 minutes of silence, so a script that
        # sleeps between bot.ai calls would be reclaimed mid-run. Sent for
        # externally-owned tasks too — this SDK is the executor, so liveness
        # is its to prove. QIRA_HEARTBEAT=0 is the troubleshooting kill switch.
        self._heartbeat: Heartbeat | None = None
        if heartbeat and os.environ.get("QIRA_HEARTBEAT", "").lower() not in ("0", "false", "no", "off"):
            self._heartbeat = Heartbeat(
                self._transport, self._task_id, on_terminated=self._on_server_terminated
            )
            self._heartbeat.start()
        # Per-run output directory, bucketed by date to avoid one flat pile:
        #   <root>/<YYYY-MM-DD>/<HHMMSS>-<task_id[:8]>/
        # report_dir / QIRA_REPORT_DIR set only the root; the date/run subdirs
        # are added automatically so one env var works across many runs.
        self._report = report
        root = report_dir or os.environ.get("QIRA_REPORT_DIR", "") or "./qira_runs"
        short = (self._task_id or "run")[:8]
        self._report_dir = (
            Path(root) / time.strftime("%Y-%m-%d") / f"{time.strftime('%H%M%S')}-{short}"
        )
        # Session-wide action timeline for the report, and the current task
        # section ai() runs are grouped under (standalone actions = "setup").
        self._log: list[dict[str, Any]] = []
        self._current_section = "setup"
        # ai() instruction -> RunStatus, for the per-section badge in the
        # report (completed / goal_failed / max_steps / error).
        self._section_outcomes: dict[str, str] = {}
        # Outcome of the most recent ai() call, driving close()'s auto-complete
        # status: a run whose last command errored must not be recorded as
        # "completed" just because close() ran (atexit after a crash included).
        # goal_failed/max_steps stay "completed" at task level — the command
        # ran; whether that fails the task is the script's call via fail().
        self._last_ai_status: str | None = None
        self._last_ai_error = ""
        # Session-wide totals for the report header. Token/timing data rides in
        # each ai() step result, not in _log, so we accumulate it here as steps
        # run and hand the totals to the report at render time.
        self._stats: dict[str, int] = {
            "ai_steps": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "step_duration_ms": 0,
            "llm_decision_duration_ms": 0,
        }
        self._screenshot_counter = 0
        self._screenshot_config = ScreenshotConfig(
            format=screenshot_format,
            quality=screenshot_quality,
            annotate=screenshot_annotate,
        )
        self._retry = retry
        self._retry_delay = retry_delay
        # Fixed delay (seconds) each adapter sleeps after a screen-changing action
        # so the next screenshot lands on the repainted frame. ``None`` keeps each
        # platform's built-in default (desktop 1.0 / mobile 0.6 / browser 0.6 /
        # airtest 1); an explicit value (incl. 0 to disable) overrides all of them.
        # Falls back to the QIRA_SETTLE_SECONDS env var when the arg is omitted.
        if settle_seconds is None:
            env_settle = os.environ.get("QIRA_SETTLE_SECONDS", "")
            if env_settle:
                try:
                    settle_seconds = float(env_settle)
                except ValueError:
                    raise ValueError(
                        f"QIRA_SETTLE_SECONDS must be a number, got {env_settle!r}"
                    )
        if settle_seconds is not None and settle_seconds < 0:
            raise ValueError(f"settle_seconds must be >= 0, got {settle_seconds}")
        self._settle_seconds = settle_seconds
        self._step_seq = 0
        # Built-in ffmpeg full-screen recording. Opt-in (default off); the
        # QIRA_RECORD env var enables it without a code change. Auto-started here
        # and stopped in close() so the mp4 is finalized before the report scans
        # for it. A single recorder slot + a fixed output path mean the auto path
        # and the manual start_recording()/stop_recording() never spawn two ffmpegs.
        self._record = record or _env_truthy(os.environ.get("QIRA_RECORD", ""))
        self._record_fps = record_fps
        # Windows-only recording extras: follow the window under test (resolved
        # lazily from the first action's target) and capture system audio.
        self._record_window = record_window or _env_truthy(os.environ.get("QIRA_RECORD_WINDOW", ""))
        # By default record_window crops a desktop grab to the window's visible
        # rect (works for GPU/game windows the per-window path renders black).
        # QIRA_RECORD_WINDOW_NATIVE=1 forces the legacy gdigrab per-window mode,
        # which can follow a background/occluded *non-GPU* window but goes black
        # on games.
        self._record_window_native = _env_truthy(os.environ.get("QIRA_RECORD_WINDOW_NATIVE", ""))
        self._record_audio = record_audio or _env_truthy(os.environ.get("QIRA_RECORD_AUDIO", ""))
        if record_audio_offset is None:
            env_off = os.environ.get("QIRA_AUDIO_OFFSET", "")
            if env_off:
                try:
                    record_audio_offset = float(env_off)
                except ValueError:
                    raise ValueError(f"QIRA_AUDIO_OFFSET must be a number, got {env_off!r}")
        self._record_audio_offset = record_audio_offset
        # Record an MJPEG stream (WDA's device-screen stream, port 9100) instead
        # of the host screen — the only way `record=True` can capture an iOS
        # device's screen rather than the desktop the SDK runs on.
        self._record_mjpeg_url = record_mjpeg_url or os.environ.get("QIRA_RECORD_MJPEG_URL", "") or None
        # Record the automated device's own screen instead of the host screen:
        # the recorder is picked from the first action's target (Appium driver
        # → session recording API; airtest Android → adb screenrecord), so the
        # start is deferred like record_window's.
        self._record_device = record_device or _env_truthy(os.environ.get("QIRA_RECORD_DEVICE", ""))
        self._recorder: Recorder | None = None
        # Epoch time the current recording started; anchors the report's
        # per-step video-seek offsets. 0.0 = no recording started this run.
        self._record_started_ts = 0.0
        # True while a recording is still owed: claimed (set False) right before a
        # recorder starts, which also guards against re-entrancy through
        # _get_adapter when window-following resolves the target.
        self._record_pending = self._record and self._report
        atexit.register(self.close)
        self._maybe_start_recording()

    def _on_server_terminated(self, status: str) -> None:
        """Heartbeat-thread callback: the server reports the task is terminal.

        One-way boolean flip (safe under the GIL, no lock needed): close()
        must not report /complete for a task the server already terminated —
        the state machine would reject it, and the local report would lie.
        The error itself surfaces on the script's next bot call via the /act
        control response; this callback never interrupts the main thread.
        """
        self._terminalized = True

    def _check_control(self, result: dict[str, Any]) -> None:
        """Raise on a /act control response before any success handling.

        ``control="terminated"`` means the task is already terminal server-side
        (console kill, orphan cleaner, max-duration cap): no step ran, nothing
        was charged, and retrying is pointless. Unknown control values (e.g. a
        future "paused" from a newer server) fall through to the normal
        failure path so this SDK doesn't misreport a recoverable state as
        terminated — the server's error message travels either way.
        """
        if result.get("control") != "terminated":
            return
        self._terminalized = True
        status = str(result.get("status", ""))
        raise TaskTerminatedError(
            result.get("error") or f"task already {status}",
            task_status=status,
        )

    @property
    def report_dir(self) -> str:
        """The per-run output directory (report.html + screenshots/ + recording).

        Pass ``record=True`` (or set ``QIRA_RECORD=1``) and the SDK records the
        full screen here as ``recording.mp4`` via ffmpeg, embedding it in the
        report automatically; :meth:`start_recording`/:meth:`stop_recording`
        drive it manually. Dropping your own ``recording.mp4`` into this dir is
        also picked up.

        Creating the directory on access keeps the recording/output patterns
        working even when nothing has been written to it yet (e.g. a run that
        crashes on its first action, before any screenshot).
        """
        self._report_dir.mkdir(parents=True, exist_ok=True)
        return str(self._report_dir)

    @property
    def task_id(self) -> str | None:
        return self._task_id

    def bind(self, target: Any) -> _BoundQirabot:
        """Bind a target once and drop it from subsequent calls.

        Returns a drop-in proxy you use exactly like this ``Qirabot``: action
        methods (``click``/``type_text``/``ai``/…) no longer take ``target`` as
        their first argument, and lifecycle/context-manager methods delegate to
        this instance::

            with Qirabot().bind(driver) as bot:
                bot.click("Login")
                bot.type_text("Email", "a@b.com")

        Best for frameworks that drive a single, stable target for the whole
        session (Airtest, pyautogui, Appium, Selenium). For Playwright's
        new-tab flows the explicit ``page = bot.click(page, ...)`` form keeps
        the returned (possibly new) page visible; with a bound proxy, reach the
        live page via ``bot.current_page()`` for native Playwright interop.
        """
        return _BoundQirabot(self, target)

    def open(
        self,
        url: str = "",
        headless: bool = False,
        *,
        viewport: tuple[int, int] = (1280, 800),
        user_data_dir: str = "",
        channel: str = "",
        args: list[str] | None = None,
        cdp_url: str = "",
    ) -> Any:
        """Launch a browser and optionally navigate to a URL.

        Args:
            url: optional URL to open. If no scheme present, ``https://`` is prepended.
            headless: run without a visible window. On Linux with no display
                server (``DISPLAY``/``WAYLAND_DISPLAY`` both unset) a headed
                launch cannot work, so ``headless=False`` falls back to
                headless with a warning.
            viewport: ``(width, height)`` in pixels. Ignored when ``cdp_url`` is set.
            user_data_dir: persistent profile directory. When set, uses
                ``launch_persistent_context`` so cookies/history/extensions persist
                across runs. Cannot be shared by two browsers at the same time.
            channel: Chromium channel (e.g. ``"chrome"``, ``"msedge"``). Uses the
                locally installed browser instead of Playwright's bundled Chromium.
            args: extra raw arguments passed to the Chromium process.
            cdp_url: connect to an already-running Chrome via CDP (e.g.
                ``"http://localhost:9222"`` or a Browserless/Browserbase ``wss://``
                endpoint) instead of launching one. Always opens a fresh tab so the
                user's existing tabs are untouched. Mutually exclusive with
                ``headless``/``user_data_dir``/``channel``/``args``.

        Returns a playwright Page object that can be passed to other methods.
        """
        sync_playwright = require("playwright.sync_api", "browser").sync_playwright

        if cdp_url and (user_data_dir or channel or args or headless):
            raise ValueError(
                "cdp_url cannot be combined with headless/user_data_dir/channel/args "
                "(those apply only when launching a browser)"
            )

        # A headed launch cannot succeed without a display server, so on a
        # display-less Linux box (typical headless VM / CI) fall back rather
        # than fail. cdp_url is exempt: it attaches to a browser that already
        # runs elsewhere.
        if (
            not headless
            and not cdp_url
            and sys.platform.startswith("linux")
            and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        ):
            logger.warning(
                "no display detected (DISPLAY/WAYLAND_DISPLAY unset) — a headed "
                "browser cannot start here; launching headless instead"
            )
            headless = True

        pw = sync_playwright().start()
        self._pw_instances.append(pw)

        viewport_dict: ViewportSize = {"width": viewport[0], "height": viewport[1]}

        if cdp_url:
            browser = pw.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            self._cdp_pages.append(page)
        elif user_data_dir:
            launch_kwargs: dict[str, Any] = {"headless": headless}
            if channel:
                launch_kwargs["channel"] = channel
            if args:
                launch_kwargs["args"] = list(args)
            context = pw.chromium.launch_persistent_context(
                user_data_dir,
                viewport=viewport_dict,
                **launch_kwargs,
            )
            page = context.pages[0] if context.pages else context.new_page()
        else:
            launch_kwargs = {"headless": headless}
            if channel:
                launch_kwargs["channel"] = channel
            if args:
                launch_kwargs["args"] = list(args)
            browser = pw.chromium.launch(**launch_kwargs)
            context = browser.new_context(viewport=viewport_dict)
            page = context.new_page()

        if url:
            if "://" not in url:
                url = "https://" + url
            page.goto(url)
        return page

    def _maybe_wait(
        self,
        target: Any,
        locate: str,
        timeout: float,
        interval: float,
        wait: str,
        model_alias: str = "",
        language: str = "",
    ) -> None:
        """Auto-wait before an action: poll until the target looks present.

        When ``timeout > 0``, block until a visual assertion holds (or raise
        :class:`QirabotTimeoutError`). The assertion is ``wait`` if given, else
        one derived from ``locate``. This is qirabot's framework-agnostic
        analogue of Playwright's auto-waiting — but it can only check *visible*
        (a vision yes/no), not stable/enabled/receives-events. It deliberately
        polls an **assertion** (verify is honest) rather than the action's
        locate (which fabricates coordinates for absent elements).
        """
        if not timeout or timeout <= 0:
            return
        assertion = wait or f"the element/button for '{locate}' is visible on screen"
        self.wait_for(
            target,
            assertion,
            timeout=timeout,
            interval=interval,
            model_alias=model_alias,
            language=language,
        )

    def click(
        self,
        target: Any,
        locate: str,
        *,
        timeout: float = 0.0,
        interval: float = 2.0,
        wait: str = "",
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> Any:
        """AI-powered click: locate element by description and click it.

        When ``timeout > 0``, auto-waits until the element looks present before
        clicking (polling a visual assertion every ``interval`` seconds), and
        raises :class:`QirabotTimeoutError` if it never appears. ``wait`` lets
        you supply that assertion explicitly; otherwise it is derived from
        ``locate``. With the default ``timeout=0`` the click is immediate.

        Returns the current target (the same kind you passed in: a Playwright
        Page, Selenium/Appium driver, or the pyautogui module). If the click
        opened a link in a new tab, this is that new tab — reassign it
        (``page = bot.click(page, ...)``) to keep operating on the active page.
        """
        self._maybe_wait(target, locate, timeout, interval, wait, model_alias, language)
        adapter = self._get_adapter(target)
        self._ai_action(
            target,
            action={"type": "click", "params": {"locate": locate}},
            model_alias=model_alias,
            language=language,
            retry=retry,
        )
        return self._result(adapter)

    def type_text(
        self,
        target: Any,
        locate: str,
        text: str,
        *,
        press_enter: bool = False,
        clear_before_typing: bool = False,
        timeout: float = 0.0,
        interval: float = 2.0,
        wait: str = "",
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> Any:
        """AI-powered type: locate input field and type text.

        When ``timeout > 0``, auto-waits until the field looks present before
        typing (see :meth:`click` for the ``timeout``/``interval``/``wait``
        semantics). With the default ``timeout=0`` it types immediately.

        Returns the current target (same kind you passed in); reassign it
        (``page = bot.type_text(page, ...)``) to follow any tab switch.
        """
        self._maybe_wait(target, locate, timeout, interval, wait, model_alias, language)
        adapter = self._get_adapter(target)
        params: dict[str, Any] = {"locate": locate, "text": text}
        if press_enter:
            params["press_enter"] = True
        if clear_before_typing:
            params["clear_before_typing"] = True
        self._ai_action(
            target,
            action={"type": "type_text", "params": params},
            model_alias=model_alias,
            language=language,
            retry=retry,
        )
        return self._result(adapter)

    def double_click(
        self,
        target: Any,
        locate: str,
        *,
        timeout: float = 0.0,
        interval: float = 2.0,
        wait: str = "",
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> Any:
        """AI-powered double-click: locate element by description and double-click it.

        When ``timeout > 0``, auto-waits until the element looks present before
        acting (see :meth:`click` for the ``timeout``/``interval``/``wait``
        semantics). With the default ``timeout=0`` it acts immediately.

        Returns the current target (same kind you passed in); reassign it
        (``page = bot.double_click(page, ...)``) to follow any tab switch.
        """
        self._maybe_wait(target, locate, timeout, interval, wait, model_alias, language)
        adapter = self._get_adapter(target)
        self._ai_action(
            target,
            action={"type": "double_click", "params": {"locate": locate}},
            model_alias=model_alias,
            language=language,
            retry=retry,
        )
        return self._result(adapter)

    def long_press(
        self,
        target: Any,
        locate: str,
        *,
        duration: float = 2.0,
        timeout: float = 0.0,
        interval: float = 2.0,
        wait: str = "",
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> Any:
        """AI-powered long press: locate element and press-and-hold it.

        Touch-only gesture (Android/iOS) for context menus, edit/select mode,
        drag-to-reorder priming, etc. ``duration`` is the hold time in seconds
        (default 2.0).

        When ``timeout > 0``, auto-waits until the element looks present before
        acting (see :meth:`click` for the ``timeout``/``interval``/``wait``
        semantics). With the default ``timeout=0`` it acts immediately.

        Returns the current target (same kind you passed in).
        """
        self._maybe_wait(target, locate, timeout, interval, wait, model_alias, language)
        adapter = self._get_adapter(target)
        params: dict[str, Any] = {"locate": locate}
        if duration != 2.0:
            # Wire convention is milliseconds (matches the server schema/wait).
            params["duration"] = int(duration * 1000)
        self._ai_action(
            target,
            action={"type": "long_press", "params": params},
            model_alias=model_alias,
            language=language,
            retry=retry,
        )
        return self._result(adapter)

    def mouse_down(
        self,
        target: Any,
        locate: str,
        *,
        timeout: float = 0.0,
        interval: float = 2.0,
        wait: str = "",
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> Any:
        """AI-powered mouse press-and-hold: locate an element and hold the
        button down on it WITHOUT releasing (pairs with :meth:`mouse_up`).

        Desktop-only primitive for drag-from / press-and-hold gestures. You are
        responsible for the matching ``mouse_up``; as a safety net any input
        still held is auto-released at the end of an :meth:`ai` run and on
        :meth:`close`.

        When ``timeout > 0``, auto-waits until the element looks present before
        acting (see :meth:`click` for the semantics).

        Returns the current target (same kind you passed in).
        """
        self._maybe_wait(target, locate, timeout, interval, wait, model_alias, language)
        adapter = self._get_adapter(target)
        self._ai_action(
            target,
            action={"type": "mouse_down", "params": {"locate": locate}},
            model_alias=model_alias,
            language=language,
            retry=retry,
        )
        return self._result(adapter)

    def mouse_up(
        self,
        target: Any,
        locate: str = "",
        *,
        timeout: float = 0.0,
        interval: float = 2.0,
        wait: str = "",
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> Any:
        """Release the mouse button (pairs with :meth:`mouse_down`).

        With ``locate`` the element is found (AI, billed) and the cursor moves
        there before releasing — i.e. drop on a target. With the default empty
        ``locate`` it releases at the current cursor position deterministically
        (no AI, no billing), like :meth:`press_key`.

        Returns the current target (same kind you passed in).
        """
        adapter = self._get_adapter(target)
        if not locate:
            adapter.execute("mouse_up", {})
            self._record_local_step(adapter, "mouse_up")
            return self._result(adapter)
        self._maybe_wait(target, locate, timeout, interval, wait, model_alias, language)
        self._ai_action(
            target,
            action={"type": "mouse_up", "params": {"locate": locate}},
            model_alias=model_alias,
            language=language,
            retry=retry,
        )
        return self._result(adapter)

    def key_down(self, target: Any, key: str) -> Any:
        """Press and HOLD a key without releasing (pairs with :meth:`key_up`).
        No AI, no billing.

        Desktop-only primitive for held-key gestures (e.g. hold ``"w"`` to keep
        moving in a game, hold ``"shift"`` to modify clicks). You are
        responsible for the matching ``key_up``; any key still held is
        auto-released at the end of an :meth:`ai` run and on :meth:`close`.

        Returns the current target (same kind you passed in).
        """
        adapter = self._get_adapter(target)
        adapter.execute("key_down", {"key": key})
        self._record_local_step(adapter, "key_down", {"key": key})
        return self._result(adapter)

    def key_up(self, target: Any, key: str) -> Any:
        """Release a key previously held with :meth:`key_down`. No AI, no billing.

        Returns the current target (same kind you passed in).
        """
        adapter = self._get_adapter(target)
        adapter.execute("key_up", {"key": key})
        self._record_local_step(adapter, "key_up", {"key": key})
        return self._result(adapter)

    def extract(
        self,
        target: Any,
        instruction: str,
        *,
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> ExtractResult:
        """Extract data from the screen using AI.

        Returns an :class:`ExtractResult` — a str subclass that is the extracted
        text, with the call's token usage attached (``input_tokens`` /
        ``output_tokens`` / ``thinking_tokens``). Usable anywhere a str is.
        """
        result = self._ai_action(
            target,
            action={"type": "extract", "params": {"instruction": instruction}},
            model_alias=model_alias,
            language=language,
            execute_result=False,
            retry=retry,
        )
        self._accumulate_stats(result)
        return ExtractResult.from_dict(result)

    def verify(
        self,
        target: Any,
        assertion: str,
        *,
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> VerifyResult:
        """Verify a visual assertion.

        Returns a :class:`VerifyResult` that is truthy when the assertion holds,
        so ``assert bot.verify(...)`` keeps working; read ``reason`` for the
        model's explanation and the token fields for this call's usage.
        """
        result = self._ai_action(
            target,
            action={"type": "assert", "params": {"assertion": assertion}},
            model_alias=model_alias,
            language=language,
            execute_result=False,
            retry=retry,
        )
        self._accumulate_stats(result)
        return VerifyResult.from_dict(result)

    def _accumulate_stats(self, result: dict[str, Any]) -> None:
        """Fold a one-shot /act result's usage into the run stats.

        verify()/extract() are single AI calls outside the ai() loop, so their
        tokens would otherwise never reach the report. Count each as an AI step
        (mirroring the ai() loop) so the summary line shows up and totals are
        complete even for pure verify/extract scripts.
        """
        self._stats["ai_steps"] += 1
        self._stats["input_tokens"] += result.get("inputTokens", 0)
        self._stats["output_tokens"] += result.get("outputTokens", 0)
        self._stats["thinking_tokens"] += result.get("thinkingTokens", 0)
        self._stats["step_duration_ms"] += result.get("stepDurationMs", 0)
        self._stats["llm_decision_duration_ms"] += result.get("llmDecisionDurationMs", 0)

    def wait_for(
        self,
        target: Any,
        assertion: str,
        timeout: float = 30.0,
        interval: float = 2.0,
        *,
        model_alias: str = "",
        language: str = "",
    ) -> None:
        """Wait until a visual condition holds, polling every ``interval`` seconds.

        Acts as an assertion/gate: returns once the condition is met, or raises
        :class:`QirabotTimeoutError` if it is still not met after ``timeout``
        seconds. For a non-raising one-shot check use :meth:`verify`, which
        returns a bool.
        """
        deadline = time.monotonic() + timeout
        while True:
            met = self.verify(target, assertion, model_alias=model_alias, language=language)
            if met:
                return
            if time.monotonic() >= deadline:
                raise QirabotTimeoutError(
                    f"wait_for timed out after {timeout:g}s: {assertion}"
                )
            time.sleep(interval)

    def ai(
        self,
        target: Any,
        instruction: str,
        max_steps: int = 20,
        *,
        on_step: Callable[[StepResult], None] | None = None,
        model_alias: str = "",
        language: str = "",
        custom_tools: list[Callable[..., Any] | dict[str, Any]] | None = None,
        exclude_tools: list[str] | None = None,
    ) -> RunResult:
        """AI-powered multi-step operation.

        Steps run by this call are grouped under ``instruction`` in the report.

        ``custom_tools`` registers your own functions as tools the model can
        call mid-task (e.g. a GM-command sender in game testing). Pass named
        functions — tool name, description, and parameters come from the
        function name, docstring, and signature — or dicts with an explicit
        schema plus a ``handler`` callable. When the model picks one, the SDK
        calls it locally and feeds the return value back to the model as the
        observation; tools run on your machine only, never server-side.

        ``exclude_tools`` removes built-in tools (by name, e.g. ``"scroll"``)
        from the model's tool list for this call; ``done`` cannot be excluded.
        """
        prev_section = self._current_section
        self._current_section = instruction or "ai"
        try:
            result = self._ai_loop(
                target,
                instruction,
                max_steps,
                on_step=on_step,
                model_alias=model_alias,
                language=language,
                custom_tools=custom_tools,
                exclude_tools=exclude_tools,
            )
            self._section_outcomes[self._current_section] = result.status
            self._last_ai_status = result.status
            self._last_ai_error = result.output if result.status == "error" else ""
            return result
        except Exception as e:
            # Any exception on the way out — ActionError, timeout, adapter
            # failure — is an "error" ending, distinct from goal_failed.
            self._section_outcomes[self._current_section] = "error"
            self._last_ai_status = "error"
            self._last_ai_error = str(e)
            raise
        finally:
            self._current_section = prev_section
            # Safety net: release any mouse button / key the model held with
            # mouse_down/key_down but never released (or that an exception
            # interrupted), so a stuck input can't corrupt later actions or
            # outlive this run. Best-effort; never mask the real result/error.
            try:
                self._get_adapter(target).release_all_inputs()
            except Exception:
                logger.debug("release_all_inputs failed after ai()", exc_info=True)

    def _ai_loop(
        self,
        target: Any,
        instruction: str,
        max_steps: int = 20,
        *,
        on_step: Callable[[StepResult], None] | None = None,
        model_alias: str = "",
        language: str = "",
        custom_tools: list[Callable[..., Any] | dict[str, Any]] | None = None,
        exclude_tools: list[str] | None = None,
    ) -> RunResult:
        adapter = self._get_adapter(target)
        steps: list[StepResult] = []
        last_action_result = ""
        last_was_save_note = False
        tool_defs, tool_handlers = build_tool_defs(custom_tools) if custom_tools else ([], {})
        sent_tool_params = bool(tool_defs or exclude_tools)

        for step_num in range(1, max_steps + 1):
            # After save_note the device hasn't moved, so reuse the cached
            # screenshot on the server side and skip a redundant upload.
            if last_was_save_note:
                screenshot_bytes = b""
            else:
                screenshot_bytes = adapter.screenshot(self._screenshot_config)
            device_info = adapter.device_info()

            # Allocate a fresh step_seq for this loop iteration. The ai() loop
            # currently does not retry a failed step, so the seq is consumed
            # exactly once per iteration. If retry is added in the future, the
            # seq must stay constant across the retry attempts.
            self._step_seq += 1

            request_body: dict[str, Any] = {
                "device_info": device_info.to_dict(),
                "step_seq": self._step_seq,
            }
            if last_action_result:
                request_body["action_result"] = last_action_result
            if step_num == 1:
                ai_params: dict[str, Any] = {"instruction": instruction, "max_steps": max_steps}
                if tool_defs:
                    ai_params["custom_tools"] = tool_defs
                if exclude_tools:
                    ai_params["exclude_tools"] = list(exclude_tools)
                request_body["action"] = {
                    "type": "ai",
                    "params": ai_params,
                }
            alias = model_alias or self._model_alias
            if alias:
                request_body["model_alias"] = alias
            lang = language or self._language
            if lang:
                request_body["language"] = lang

            files: dict[str, tuple[str, bytes, str]] = {}
            if screenshot_bytes:
                files["screenshot"] = (
                    f"screenshot.{self._screenshot_config.extension}",
                    screenshot_bytes,
                    self._screenshot_config.mime_type,
                )

            result = self._post_act_retrying(
                files=files,
                data={"request": json.dumps(request_body)},
            )
            self._check_control(result)

            if not result.get("success"):
                error_msg = result.get("error", "AI request failed")
                if result.get("finished"):
                    logger.error("failed: %s", error_msg)
                    # Record the failure so the report shows *why* the task
                    # ended — otherwise this branch returns silently and the
                    # error reason never reaches the timeline.
                    self._record_step(
                        screenshot_bytes,
                        result.get("actionType") or "ai",
                        result.get("params") or {},
                        output=error_msg,
                        finished=True,
                        success=False,
                    )
                    return RunResult(
                        success=False, output=error_msg, steps=steps, status="error"
                    )
                raise ActionError(error_msg)

            if warning := result.get("warning"):
                logger.warning("%s", warning)
            if step_num == 1 and sent_tool_params:
                # Only successful responses go through NewStepResponse, so the
                # echo's absence there is meaningful; error bodies never carry it.
                registration = result.get("tool_registration")
                if registration:
                    logger.info(
                        "custom tools registered: %s; excluded: %s",
                        registration.get("registered") or [],
                        registration.get("excluded") or [],
                    )
                else:
                    logger.warning(
                        "server does not support custom_tools/exclude_tools; "
                        "tools will not take effect"
                    )

            action_type = result.get("actionType")
            action_params = result.get("params") or {}
            finished = result.get("finished", False)
            decision = result.get("decision", "")

            coords = _extract_coords(action_params)
            entry = self._record_step(
                screenshot_bytes,
                action_type or "ai",
                action_params,
                coords,
                end_coords=_extract_end_coords(action_params),
                output=result.get("output", ""),
                finished=finished,
                decision=decision,
                coord_scale=adapter.annotation_scale(),
            )

            if logger.isEnabledFor(logging.INFO):
                parts = [f"step {step_num}/{max_steps}"]
                if decision:
                    parts.append(decision)
                parts.append(f"-> {action_type}")
                detail_parts = []
                if "locate" in action_params:
                    detail_parts.append(f'"{action_params["locate"]}"')
                if "text" in action_params:
                    detail_parts.append(f'text="{action_params["text"]}"')
                if "direction" in action_params:
                    detail_parts.append(f'{action_params["direction"]} {action_params.get("amount", "")}')
                if detail_parts:
                    parts.append(f"({', '.join(detail_parts)})")
                logger.info("%s", " ".join(parts))

            step_result = StepResult.from_dict(result, step_num)
            steps.append(step_result)

            self._stats["ai_steps"] += 1
            self._stats["input_tokens"] += step_result.input_tokens
            self._stats["output_tokens"] += step_result.output_tokens
            self._stats["thinking_tokens"] += step_result.thinking_tokens
            self._stats["step_duration_ms"] += step_result.step_duration_ms
            self._stats["llm_decision_duration_ms"] += step_result.llm_decision_duration_ms

            if on_step:
                on_step(step_result)

            if finished:
                output = result.get("output", "")
                # The done action carries the model's own success flag: false
                # means it concluded the goal is unreachable (login wall,
                # captcha, the app froze). It rides in the action params; the
                # top-level `success` checked above only means "the step
                # committed". The server records this same outcome as the task's
                # terminal state (mirroring max-steps). Default true for older
                # servers that omit the flag.
                goal_ok = bool(action_params.get("success", True))
                # Log a short completion marker, not the full output: the result
                # text is the caller's to surface via result.output, and dumping
                # it here duplicates that for any caller that prints the result
                # (and is out of step with the short per-step progress lines).
                logger.info("completed in %d step(s)", len(steps))
                return RunResult(
                    success=goal_ok,
                    output=output,
                    steps=steps,
                    status="completed" if goal_ok else "goal_failed",
                )

            if action_type and action_type != "done":
                try:
                    if action_type in tool_handlers:
                        # Custom tool: run the user's handler instead of a
                        # device action. Params are exactly the model's args
                        # for the registered schema (the server strips its
                        # meta fields). The return value is the observation
                        # fed back to the model on the next request —
                        # "ok" if result is None, NOT str(result) or "ok":
                        # str(None) is the truthy string "None".
                        ret = tool_handlers[action_type](**action_params)
                        last_action_result = "ok" if ret is None else str(ret)
                    else:
                        self._execute_action(adapter, result)
                        last_action_result = "ok"
                except Exception as e:
                    last_action_result = f"ERROR: {e}"
                    # The step's screenshot/decision were recorded before this
                    # action ran, so its outcome only surfaces now. Backfill the
                    # entry so the report marks it failed (red ✗) and shows why,
                    # instead of leaving an errored step looking successful. The
                    # loop still continues — the error is fed back so the model
                    # can recover on the next step.
                    if entry is not None:
                        entry["success"] = False
                        err = f"execution failed: {e}"
                        entry["output"] = (
                            f"{entry['output']}\n{err}" if entry["output"] else err
                        )

            last_was_save_note = action_type == "save_note"

        # A truncation, not an error: the budget ran out before the model
        # finished. warning-level, and the recorded step is marked warn so the
        # report tints it amber instead of failure red.
        logger.warning("stopped: step budget exhausted (%d/%d)", max_steps, max_steps)
        self._record_step(
            screenshot_bytes,
            "ai",
            {"instruction": instruction, "max_steps": max_steps},
            output="max steps reached",
            finished=True,
            success=False,
            warn=True,
        )
        # Output string is load-bearing: callers may match "max steps reached".
        return RunResult(
            success=False, output="max steps reached", steps=steps, status="max_steps"
        )

    def screenshot(self, target: Any) -> Path | None:
        """Take a screenshot and save it to ``report_dir/screenshots/``.

        Returns the saved file path, or ``None`` when ``report=False``. No AI,
        no billing.
        """
        adapter = self._get_adapter(target)
        data = adapter.screenshot(self._screenshot_config)
        return self._save_frame(data, "manual")

    def _maybe_start_recording(self, target: Any = None) -> None:
        """Auto-start screen recording when ``record=True``.

        Called once from ``__init__`` (no ``target``) and again from
        :meth:`_get_adapter` on every action (with the action's ``target``).
        Skipped once a recorder exists or the slot has been claimed. In
        ``record_window`` mode the start is deferred until an action supplies a
        ``target`` to resolve the window from. Best-effort via
        :meth:`start_recording` — a missing ffmpeg / unsupported platform warns.
        """
        if self._recorder is not None or not self._record_pending:
            return
        if (
            (self._record_window or self._record_device)
            and target is None
            and not self._record_mjpeg_url
        ):
            return  # defer: need a target to resolve the window/device from
        # Claim the slot BEFORE starting so the _get_adapter() call made while
        # resolving the window doesn't re-enter this and start a second ffmpeg.
        self._record_pending = False
        self.start_recording(target=target)

    def _resolve_window_target(self, target: Any) -> str | None:
        """Window title (or handle) to record for ``target``, or ``None``.

        Reads the adapter's :meth:`~qirabot.adapters.base.DeviceAdapter.window_info`
        (only airtest/Windows returns one); prefers the title, falls back to the
        numeric handle. Any failure degrades to ``None`` (full-screen).
        """
        try:
            info = self._get_adapter(target).window_info()
        except Exception:
            logger.debug("window_info() failed; recording full screen", exc_info=True)
            return None
        if not info:
            return None
        title = info.get("title")
        if title:
            return str(title)
        hwnd = info.get("hwnd")
        return str(hwnd) if hwnd is not None else None

    def _resolve_window_region(self, target: Any) -> tuple[int, int, int, int] | None:
        """Visible (x, y, w, h) of ``target``'s window for desktop-crop recording.

        Reads the adapter's ``window_info()`` hwnd and resolves its physical-px
        rect via :func:`qirabot.recording.window_region`. Returns ``None`` (so
        the caller degrades to per-window or full-screen) when there's no hwnd or
        the rect can't be resolved.
        """
        try:
            info = self._get_adapter(target).window_info()
        except Exception:
            logger.debug("window_info() failed; not using region capture", exc_info=True)
            return None
        hwnd = info.get("hwnd") if info else None
        if hwnd is None:
            return None
        from qirabot.recording import window_region

        return window_region(int(hwnd))

    def start_recording(
        self,
        *,
        fps: int | None = None,
        target: Any = None,
        window: str | None = None,
        audio: bool | str | None = None,
    ) -> bool:
        """Start ffmpeg recording into ``report_dir/recording.mp4``.

        Records the full screen by default. Two settings switch it to the
        *device's* screen instead (window/audio options below don't apply):
        ``record_mjpeg_url`` (or ``QIRA_RECORD_MJPEG_URL``) records that MJPEG
        stream — e.g. WDA's iOS device-screen stream on port 9100 — and
        ``record_device`` (or ``QIRA_RECORD_DEVICE``) picks a recorder from the
        action ``target``: an Appium driver uses the session recording API
        (stopped automatically before the report; callers quitting the driver
        themselves must call :meth:`stop_recording` first), an airtest Android
        device uses ``adb screenrecord``. On Windows it can instead follow a
        single window and capture system audio:

        * ``window`` — a window title (or numeric handle) to record via legacy
          per-window capture.
        * ``target`` — when ``record_window`` is set, the window is resolved
          automatically from this action target (airtest/Windows only). By
          default its visible rect is cropped out of a desktop grab (works for
          GPU/game windows); set ``QIRA_RECORD_WINDOW_NATIVE=1`` to force the
          legacy per-window mode instead.
        * ``audio`` — ``True`` to auto-detect a system-audio device, a dshow
          device name, or ``False``; defaults to the ``record_audio`` setting.

        Idempotent: if a recording is already running, this is a no-op returning
        ``True``. The file is finalized and embedded in the report on
        :meth:`close`. Best-effort — returns ``False`` (and only warns) when
        ffmpeg is missing or the platform is unsupported.

        Note: starting again after :meth:`stop_recording` overwrites the same
        ``recording.mp4`` (it re-records from scratch, it does not resume).
        """
        if self._recorder is not None and self._recorder.active:
            logger.info("recording already in progress; ignoring start_recording()")
            return True
        # Manual start also claims the slot so a later action's auto-start hook
        # doesn't spawn a second recorder.
        self._record_pending = False
        output = os.path.join(self.report_dir, "recording.mp4")
        recorder: Recorder | None
        if self._record_mjpeg_url:
            # Device-screen stream (WDA MJPEG): window/region/audio are
            # host-screen concepts and don't apply.
            recorder = MjpegStreamRecorder(output, self._record_mjpeg_url)
        elif self._record_device:
            # Device-screen recording resolved from the action target (Appium
            # driver / airtest Android). Falling back to the host screen would
            # record the wrong thing (the desktop the SDK runs on), so an
            # unsupported target skips recording — the report then carries the
            # requested-but-not-produced notice.
            recorder = device_recorder(output, target)
            if recorder is None:
                logger.warning(
                    "record: don't know how to record the device screen for %s "
                    "(need an Appium driver or an airtest Android device); recording skipped",
                    type(target).__name__,
                )
                return False
        else:
            region: tuple[int, int, int, int] | None = None
            if window is None and target is not None and self._record_window:
                # Default: crop a desktop grab to the window's visible rect (GPU/game
                # safe). Fall back to legacy per-window capture when forced via
                # QIRA_RECORD_WINDOW_NATIVE or when the rect can't be resolved
                # (non-Windows, no hwnd, DWM off).
                if not self._record_window_native:
                    region = self._resolve_window_region(target)
                if region is None:
                    window = self._resolve_window_target(target)
            audio_spec = audio if audio is not None else self._record_audio
            recorder = ScreenRecorder(
                output,
                fps=fps if fps is not None else self._record_fps,
                window=window,
                region=region,
                audio=audio_spec,
                audio_offset=self._record_audio_offset,
            )
        started = recorder.start()
        self._recorder = recorder if started else None
        if started:
            # A restart overwrites recording.mp4 from scratch, so the anchor
            # moves with it.
            self._record_started_ts = time.time()
        return started

    def stop_recording(self) -> str | None:
        """Stop the current recording and return the saved path (or ``None``).

        A no-op returning ``None`` when nothing is recording.
        """
        if self._recorder is None:
            return None
        recorder = self._recorder
        self._recorder = None
        try:
            return recorder.stop()
        except Exception:
            logger.debug("failed to stop recording", exc_info=True)
            return None

    def launch_app(self, app: str, *, wait: float = 2.0) -> None:
        """Launch (or activate) a desktop application before driving it.

        Convenience wrapper over :func:`qirabot.launch_app` for desktop
        (pyautogui) automation, which otherwise has no way to open an app. No
        AI, no billing. See that function for platform behaviour (macOS ``open``,
        Windows ``start``/``startfile``, Linux exec) and the ``app``/``wait``
        semantics.
        """
        from qirabot._applaunch import launch_app

        launch_app(app, wait=wait)

    def go_back(self, target: Any) -> Any:
        """Navigate back to the previous page/screen. No AI, no billing.

        On Playwright this is smart about tabs: if the current page has back
        history it goes back in place; if it doesn't (e.g. a click opened a link
        in a NEW tab, which starts with no history) and another tab exists, it
        closes the current tab and returns to the previous one.

        Supported on browser (Playwright, Selenium) and mobile (Appium)
        targets. Desktop (pyautogui) has no back concept and raises
        ``NotImplementedError``.

        Returns the current page/target (may differ after the navigation).
        """
        adapter = self._get_adapter(target)
        adapter.go_back()
        self._record_local_step(adapter, "go_back")
        return self._result(adapter)

    def close_tab(self, target: Any) -> Any:
        """Close the current browser tab and switch to the remaining one.

        Use this (not :meth:`go_back`) when a click opened a link in a NEW tab:
        a fresh tab has no history, so ``go_back`` is a no-op there — closing it
        is what returns you to the previous tab. No AI, no billing.

        Playwright only; other targets raise ``NotImplementedError``.

        Returns the now-current page after switching back.
        """
        adapter = self._get_adapter(target)
        adapter.close_tab()
        self._record_local_step(adapter, "close_tab")
        return self._result(adapter)

    def navigate(self, target: Any, url: str) -> Any:
        """Navigate the target to ``url``. No AI, no billing.

        If ``url`` has no scheme, ``https://`` is prepended. Supported on
        browser (Playwright, Selenium) and mobile (Appium) targets; desktop
        (pyautogui) raises ``NotImplementedError``.

        Returns the current page/target (may differ after the navigation).
        """
        if "://" not in url:
            url = "https://" + url
        adapter = self._get_adapter(target)
        adapter.navigate(url)
        self._record_local_step(adapter, "navigate", {"url": url})
        return self._result(adapter)

    def scroll(self, target: Any, direction: str = "down", distance: int = 3, *, x: float | None = None, y: float | None = None) -> None:
        """Scroll the target. No AI, no billing.

        Supported on all platforms (browser, mobile, desktop). ``direction`` is
        one of ``"up"``/``"down"``/``"left"``/``"right"``; ``distance`` is in
        scroll units (roughly ``distance * 100`` px). By default scrolls at the
        viewport center; pass ``x``/``y`` (screenshot pixels) to scroll at a
        specific point.
        """
        adapter = self._get_adapter(target)
        if x is None or y is None:
            info = adapter.device_info()
            x = info.width / 2 if x is None else x
            y = info.height / 2 if y is None else y
        adapter.scroll(float(x), float(y), direction, int(distance))
        self._record_local_step(
            adapter, "scroll",
            {"direction": direction, "amount": distance}, (float(x), float(y)),
        )

    def press_key(self, target: Any, key: str) -> Any:
        """Press a key or key combo. No AI, no billing.

        ``key`` is a single key (``"Enter"``, ``"Escape"``, ``"ArrowDown"``) or a
        combo joined with ``+`` (``"ctrl+c"``, ``"alt+tab"``). Each backend maps
        the name to its own vocabulary, so the same call works across Playwright,
        Selenium, Appium, Airtest and pyautogui — Android/iOS take single keycodes
        (``"Back"``/``"Home"``/``"Enter"``); ctrl-style combos are desktop/browser
        only.

        Returns the current target (same kind you passed in). On Playwright a
        combo that opens/closes a tab (``ctrl+t``/``ctrl+w``) switches the active
        page, so reassign it (``page = bot.press_key(page, "ctrl+t")``).
        """
        adapter = self._get_adapter(target)
        adapter.execute("press_key", {"key": key})
        self._record_local_step(adapter, "press_key", {"key": key})
        return self._result(adapter)

    def _record_step(
        self,
        data: bytes,
        action_type: str,
        params: dict[str, Any] | None,
        coords: tuple[float, float] | None = None,
        *,
        end_coords: tuple[float, float] | None = None,
        output: str = "",
        finished: bool = False,
        success: bool = True,
        warn: bool = False,
        decision: str = "",
        coord_scale: float = 1.0,
    ) -> dict[str, Any] | None:
        """Save the screenshot (if reporting) and append a step to the timeline.

        Returns the appended log entry so the caller can backfill fields that
        only become known after recording (e.g. an action's execution result),
        or ``None`` when reporting is off and nothing was recorded.

        ``assert`` actions (verify / wait_for polls) are recorded like any other
        step: the server keeps them anyway, and the poll frames are the key
        evidence when a ``wait_for`` times out.
        """
        # Reporting off → zero overhead.
        if not self._report:
            return None
        # Annotation + thumbnailing share a single PIL decode; never let a
        # malformed/unexpected screenshot break the actual action — degrade to
        # the raw bytes / no thumbnail instead.
        annotated = data
        thumb = ""
        if data:
            try:
                annotated, thumb = _render_step_images(
                    data,
                    coords,
                    self._screenshot_config,
                    end_coords=end_coords,
                    coord_scale=coord_scale,
                )
            except Exception:
                logger.debug("render step images failed", exc_info=True)
        frame = self._save_frame(annotated, action_type or "action") if data else None
        entry: dict[str, Any] = {
            "section": self._current_section,
            "ts": time.time(),
            "action_type": action_type or "",
            "params": params or {},
            "decision": decision or "",
            "output": output or "",
            "finished": bool(finished),
            "success": bool(success),
            "coords": list(coords) if coords else None,
            # relative to report_dir so the html can link it directly
            "screenshot": f"screenshots/{frame.name}" if frame else "",
            "thumb": thumb,
        }
        # warn marks a truncation (max steps), not a failure — the report
        # renders it amber instead of red. Only set when true to keep the log
        # lean and older entries unchanged.
        if warn:
            entry["warn"] = True
        self._log.append(entry)
        return entry

    def _record_local_step(
        self,
        adapter: DeviceAdapter,
        action_type: str,
        params: dict[str, Any] | None = None,
        coords: tuple[float, float] | None = None,
    ) -> None:
        """Record a deterministic (non-AI) action in the local report.

        Primitives like :meth:`press_key` / :meth:`scroll` drive the adapter
        directly and bypass ``/act``, so the server never sees them and they
        were previously invisible in the report. Capture a post-action
        screenshot and append a step, mirroring what :meth:`_ai_action` does
        for AI actions. Best-effort: reporting off → zero overhead, and a
        failure to capture or persist the frame must never break the action
        itself — recording is a side channel, not part of the operation.
        """
        if not self._report:
            return
        try:
            data = adapter.screenshot(self._screenshot_config)
            # Only record once we actually have image bytes; anything else
            # (a stubbed adapter, a backend returning None) is skipped rather
            # than written to disk.
            if isinstance(data, (bytes, bytearray)):
                self._record_step(
                    bytes(data),
                    action_type,
                    params or {},
                    coords,
                    end_coords=_extract_end_coords(params),
                    coord_scale=adapter.annotation_scale(),
                )
        except Exception:
            logger.debug("local step recording failed", exc_info=True)

    def _save_frame(self, data: bytes, label: str) -> Path | None:
        """Write a full-resolution screenshot to ``report_dir/screenshots/``."""
        if not self._report:
            return None
        dir_path = self._report_dir / "screenshots"
        dir_path.mkdir(parents=True, exist_ok=True)
        self._screenshot_counter += 1
        filename = f"{self._screenshot_counter:03d}_{label}.{self._screenshot_config.extension}"
        path = dir_path / filename
        path.write_bytes(data)
        logger.debug("screenshot saved: %s", path)
        return path

    def current_page(self, target: Any) -> Any:
        """Return the actual current page/target (may differ from the original after tab switches)."""
        return self._result(self._get_adapter(target))

    def _get_adapter(self, target: Any) -> DeviceAdapter:
        adapter = self._adapters.get(id(target))
        if adapter is None:
            adapter = auto.detect(target)
            if self._settle_seconds is not None:
                adapter._settle_override = self._settle_seconds
            self._cache_adapter(target, adapter)
        # Deferred recording start for record_window mode: the first action to
        # supply a target lets us resolve the window to follow. Cheap no-op once
        # started/claimed (and re-entrancy-safe via _record_pending).
        if self._record_pending:
            self._maybe_start_recording(target)
        return adapter

    def _cache_adapter(self, target: Any, adapter: DeviceAdapter) -> None:
        """Cache ``adapter`` under ``id(target)``, evicting the entry when the
        target is garbage-collected.

        The cache is keyed by ``id()`` because targets aren't always hashable.
        Without eviction that has two failure modes: the dict grows unbounded
        as a long session churns through tabs/pages, and — worse — once a target
        is collected CPython can hand its ``id()`` to an unrelated object, so a
        stale adapter would be returned for it. A weakref finalizer drops the
        entry the moment the target dies, which bounds the cache and closes the
        id-reuse window. Targets that don't support weak references (rare) fall
        back to plain, un-evicted caching.
        """
        key = id(target)
        if key not in self._adapters:
            try:
                weakref.finalize(target, self._adapters.pop, key, None)
            except TypeError:
                pass  # target not weak-referenceable; keep plain caching
        self._adapters[key] = adapter

    def _result(self, adapter: DeviceAdapter) -> Any:
        """Return the adapter's current target, keeping the cache in sync.

        After a tab switch the active page is a *different* object than the one
        originally passed in. Adapters are cached by ``id(target)``, so if the
        caller passes that new page back (the common ``page = bot.click(page,
        ...)`` pattern), ``_get_adapter`` would otherwise spawn a second adapter
        that tracks its tabs independently and drifts out of sync (e.g. holding a
        tab another adapter has closed). Registering the returned object against
        this same adapter keeps exactly one adapter following the active tab.
        """
        target = adapter.current_target
        self._cache_adapter(target, adapter)
        return target

    def _post_act_retrying(
        self, files: dict[str, tuple[str, bytes, str]], data: dict[str, str]
    ) -> dict[str, Any]:
        """POST to /act, retrying transient errors with exponential backoff.

        The ai() loop allocates ``step_seq`` once per iteration and keeps it
        constant inside ``data`` across attempts, so a retry after a 5xx or
        network blip hits the server's idempotency cache and replays the prior
        response instead of triggering a second LLM call + credit charge. This
        gives the multi-step loop the same resilience the single-action path
        already gets from _ai_action.
        """
        max_attempts = self._retry + 1
        for attempt in range(max_attempts):
            try:
                return self._transport.post_multipart(
                    f"/tasks/{self._task_id}/act", files=files, data=data,
                )
            except QirabotError as e:
                if not _is_retryable(e) or attempt >= max_attempts - 1:
                    raise
                delay = self._retry_delay * (2 ** attempt)
                logger.warning(
                    "attempt %d/%d failed: %s, retrying in %.1fs...",
                    attempt + 1, max_attempts, e, delay,
                )
                time.sleep(delay)
        raise RuntimeError("unreachable")

    def _ai_action(
        self,
        target: Any,
        action: dict[str, Any],
        model_alias: str = "",
        language: str = "",
        execute_result: bool = True,
        retry: int | None = None,
    ) -> dict[str, Any]:
        """Send an AI action request and optionally execute the result.

        The step_seq nonce is allocated ONCE outside the retry loop and
        threaded through every attempt. That way a retry after a 5xx or
        network timeout hits the server's idempotency cache and replays the
        prior response instead of triggering a second LLM call + credit
        charge.
        """
        max_attempts = (retry if retry is not None else self._retry) + 1

        self._step_seq += 1
        step_seq = self._step_seq

        for attempt in range(max_attempts):
            try:
                return self._ai_action_once(
                    target, action,
                    model_alias=model_alias,
                    language=language,
                    execute_result=execute_result,
                    step_seq=step_seq,
                )
            except QirabotError as e:
                if not _is_retryable(e) or attempt >= max_attempts - 1:
                    raise
                delay = self._retry_delay * (2 ** attempt)
                logger.warning(
                    "attempt %d/%d failed: %s, retrying in %.1fs...",
                    attempt + 1, max_attempts, e, delay,
                )
                time.sleep(delay)

        raise RuntimeError("unreachable")

    def _ai_action_once(
        self,
        target: Any,
        action: dict[str, Any],
        model_alias: str = "",
        language: str = "",
        execute_result: bool = True,
        step_seq: int | None = None,
    ) -> dict[str, Any]:
        """Single attempt of an AI action request."""
        adapter = self._get_adapter(target)
        screenshot_bytes = adapter.screenshot(self._screenshot_config)
        device_info = adapter.device_info()

        request_body: dict[str, Any] = {
            "action": action,
            "device_info": device_info.to_dict(),
        }
        if step_seq is not None:
            request_body["step_seq"] = step_seq
        alias = model_alias or self._model_alias
        if alias:
            request_body["model_alias"] = alias
        lang = language or self._language
        if lang:
            request_body["language"] = lang

        result = self._transport.post_multipart(
            f"/tasks/{self._task_id}/act",
            files={"screenshot": (f"screenshot.{self._screenshot_config.extension}", screenshot_bytes, self._screenshot_config.mime_type)},
            data={"request": json.dumps(request_body)},
        )
        self._check_control(result)

        if not result.get("success"):
            raise ActionError(result.get("error", "AI request failed"))

        coords = _extract_coords(result.get("params"))
        self._record_step(
            screenshot_bytes,
            result.get("actionType") or action.get("type", "action"),
            result.get("params") or action.get("params") or {},
            coords,
            end_coords=_extract_end_coords(result.get("params")),
            output=result.get("output", ""),
            finished=result.get("finished", False),
            success=result.get("success", True),
            coord_scale=adapter.annotation_scale(),
        )

        if execute_result and result.get("actionType"):
            self._execute_action(adapter, result)

        return result

    def _execute_action(self, adapter: DeviceAdapter, resp_action: dict[str, Any]) -> None:
        action_type = resp_action.get("actionType", "")
        params = resp_action.get("params", {})
        adapter.execute(action_type, params)

    def fail(self, error_message: str = "") -> None:
        """Report a client-side failure so the task is recorded as failed.

        Use this when the run is aborted by an error on the client (e.g. your
        script catches an exception) and you want to attach your own error
        message or fail regardless of the last command's outcome. As a safety
        net, close() already records the task as failed when the most recent
        ai() call errored — fail() lets you be explicit and covers errors
        outside ai(). Idempotent and a no-op for externally owned tasks. The
        server's state machine rejects a later completion once the task is
        failed, so a subsequent close() cannot override it.
        """
        if self._terminalized:
            return
        self._terminalized = True
        if self._task_id is not None and not self._external_task:
            try:
                self._transport.post(
                    f"/tasks/{self._task_id}/complete",
                    json_data={"status": "failed", "errorMessage": error_message},
                )
            except Exception:
                logger.debug("failed to report failure for task %s", self._task_id)

    def cancel(self, reason: str = "") -> None:
        """Report a deliberate client-side abort (e.g. Ctrl+C) so the task is
        recorded as cancelled rather than failed or, worse, completed.

        Like fail(), but the server records a distinct 'cancelled' terminal state
        kept out of the failure bucket. Shares fail()'s terminalized guard so it
        is idempotent and a later close() cannot override it; a no-op for
        externally owned tasks.
        """
        if self._terminalized:
            return
        self._terminalized = True
        if self._task_id is not None and not self._external_task:
            try:
                self._transport.post(
                    f"/tasks/{self._task_id}/complete",
                    json_data={"status": "cancelled", "errorMessage": reason},
                )
            except Exception:
                logger.debug("failed to report cancellation for task %s", self._task_id)

    def report(self, path: str | None = None) -> Path | None:
        """Write the run report HTML now and return its path.

        Auto-called on :meth:`close` when ``report=True``; call manually only to
        force a custom location or an early snapshot. Returns ``None`` when there
        is nothing to report.
        """
        out = Path(path) if path else (self._report_dir / "report.html")
        return self._write_report(out)

    def _write_report(self, out: Path | None = None) -> Path | None:
        if not self._report or not self._log:
            return None
        from qirabot import report as _report

        out = out or (self._report_dir / "report.html")
        mp4 = self._report_dir / "recording.mp4"
        recording = "recording.mp4" if (mp4.exists() and mp4.stat().st_size > 0) else ""
        still_recording = self._recorder is not None and self._recorder.active
        record_error = ""
        if self._record and not recording and not still_recording:
            record_error = (
                "Recording was requested but not produced — is ffmpeg installed? "
                "(see recording.ffmpeg.log)"
            )
        try:
            _report.write_html(
                self._log,
                out,
                title=self._task_name or "",
                task_id=self._task_id or "",
                outcomes=self._section_outcomes,
                recording=recording,
                recording_start=self._record_started_ts if recording else 0.0,
                record_error=record_error,
                stats=self._stats,
                model=self._model_alias,
            )
            logger.info("report written: %s", out)
            return out
        except Exception:
            logger.debug("failed to write report", exc_info=True)
            return None

    def close(self) -> None:
        """Clean up all resources."""
        if self._closed:
            return
        self._closed = True
        # Stop the heartbeat first so no beat is in flight when the transport
        # closes below; the thread is a daemon, so a stuck request can only
        # cost the 2s join grace, never hang shutdown.
        if self._heartbeat is not None:
            self._heartbeat.stop()
        # The report is the primary artifact of an aborted run, so guarantee it
        # even if the user mashes Ctrl+C during shutdown: SIGINT is suppressed
        # for this whole block (recording finalize + report write). A plain
        # try/except can't promise this — each Ctrl+C raises a fresh
        # KeyboardInterrupt at an arbitrary point, including inside the write.
        # Worst case ffmpeg is slow to finalize and Ctrl+C is unresponsive for a
        # few seconds (stop_recording is bounded by its own timeouts); normal
        # finalize is sub-second. The try/except blocks below are the fallback
        # for the non-main-thread case where suppression is a no-op.
        with _suppress_sigint():
            # Finalize any in-progress screen recording first so the mp4 is
            # complete on disk (moov atom flushed) when _write_report scans
            # report_dir for it.
            if self._recorder is not None:
                try:
                    self.stop_recording()
                except BaseException:
                    logger.debug("recording teardown interrupted", exc_info=True)
            # Emit the run report before tearing down. Runs on normal exit,
            # exception (via __exit__), and atexit.
            try:
                self._write_report()
            except BaseException:
                logger.debug("report write interrupted", exc_info=True)
        # Auto-complete when no terminal status was reported yet. Status
        # follows the last ai() outcome: a run whose final command errored is
        # recorded failed, not completed — this covers scripts that crash out
        # of ai() and never reach fail() (close() then runs via atexit).
        # An explicit fail()/cancel() beforehand always wins (_terminalized).
        if self._task_id is not None and not self._external_task and not self._terminalized:
            self._terminalized = True
            try:
                if self._last_ai_status == "error":
                    self._transport.post(
                        f"/tasks/{self._task_id}/complete",
                        json_data={
                            "status": "failed",
                            "errorMessage": self._last_ai_error or "run ended after an errored command",
                        },
                    )
                else:
                    self._transport.post(f"/tasks/{self._task_id}/complete")
            except Exception:
                logger.debug("failed to complete task %s on close", self._task_id)
        # Let adapters unhook framework listeners (e.g. Playwright's "page"
        # event) before we tear down the contexts they're attached to. Several
        # cache keys can map to one adapter, so de-dup by identity.
        seen: set[int] = set()
        for adapter in self._adapters.values():
            if id(adapter) in seen:
                continue
            seen.add(id(adapter))
            # Backstop for scripted holds: release any input left held by
            # mouse_down/key_down before tearing the adapter down.
            try:
                adapter.release_all_inputs()
            except Exception:
                pass
            try:
                adapter.close()
            except Exception:
                pass
        self._adapters.clear()
        for page in self._cdp_pages:
            try:
                page.close()
            except Exception:
                pass
        self._cdp_pages.clear()
        for pw in self._pw_instances:
            try:
                pw.stop()
            except Exception:
                pass
        self._pw_instances.clear()
        try:
            self._transport.close()
        except Exception:
            pass
        atexit.unregister(self.close)

    def __enter__(self) -> Qirabot:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        # An exception leaving the with-block means the run aborted: report it
        # instead of letting close() complete it as a success. A KeyboardInterrupt
        # (Ctrl+C) is a deliberate cancel, not a failure.
        if isinstance(exc_val, KeyboardInterrupt):
            self.cancel("aborted by user")
        elif exc_val is not None:
            self.fail(str(exc_val))
        self.close()


def _env_truthy(value: str) -> bool:
    """Parse a boolean-ish env var value (``1``/``true``/``yes``/``on``)."""
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _extract_coords(params: dict[str, Any] | None) -> tuple[float, float] | None:
    if not params:
        return None
    x = params.get("x")
    y = params.get("y")
    if x is not None and y is not None:
        return (float(x), float(y))
    return None


def _extract_end_coords(
    params: dict[str, Any] | None,
) -> tuple[float, float] | None:
    """Drag's terminal point; used together with ``_extract_coords`` (= start)
    so the report can draw the full start→end path, not just the anchor."""
    if not params:
        return None
    x = params.get("end_x")
    y = params.get("end_y")
    if x is not None and y is not None:
        return (float(x), float(y))
    return None


def _render_step_images(
    data: bytes,
    coords: tuple[float, float] | None,
    config: ScreenshotConfig | None = None,
    *,
    end_coords: tuple[float, float] | None = None,
    coord_scale: float = 1.0,
    thumb_max_edge: int = 800,
    thumb_quality: int = 60,
) -> tuple[bytes, str]:
    """Decode the screenshot once → (full-res encoded bytes, thumbnail data URI).

    Annotates a crosshair at ``coords`` when given and ``config.annotate`` is on;
    otherwise the full-res output is just the source re-encoded in the configured
    format. ``end_coords`` is drag's terminal point — when set, a line + arrow is
    drawn from ``coords`` to it and a hollow ring marks the end. ``coord_scale``
    maps the model's coordinate space onto the screenshot pixel space — 1.0
    everywhere except Appium iOS, where coords arrive in logical points and the
    screenshot is at physical Retina pixels. The thumbnail is always a downscaled
    JPEG embedded as a data URI so the HTML report stays self-contained.
    """
    import base64
    import math

    from PIL import Image, ImageDraw

    cfg = config or ScreenshotConfig()
    img: Image.Image = Image.open(io.BytesIO(data))

    if coords is not None and cfg.annotate:
        img = img.convert("RGBA")
        draw = ImageDraw.Draw(img)
        color = (255, 0, 0, 255)
        short_side = min(img.width, img.height)
        radius = max(4, round(short_side * 0.015))
        line_len = int(radius * 1.5)
        width = 3 if short_side > 2000 else 2
        gap = radius + 2
        cx, cy = int(coords[0] * coord_scale), int(coords[1] * coord_scale)
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            outline=color, width=width,
        )
        draw.line([(cx - gap - line_len, cy), (cx - gap, cy)], fill=color, width=width)
        draw.line([(cx + gap, cy), (cx + gap + line_len, cy)], fill=color, width=width)
        draw.line([(cx, cy - gap - line_len), (cx, cy - gap)], fill=color, width=width)
        draw.line([(cx, cy + gap), (cx, cy + gap + line_len)], fill=color, width=width)

        if end_coords is not None:
            ex, ey = int(end_coords[0] * coord_scale), int(end_coords[1] * coord_scale)
            dx, dy = ex - cx, ey - cy
            dist = math.hypot(dx, dy)
            # Skip degenerate drags (start == end) — a zero-length arrow would
            # just draw an artifact on top of the start cross.
            if dist >= 1:
                ux, uy = dx / dist, dy / dist
                # Stop the shaft outside the end ring so they don't overlap.
                sx = cx + int(ux * (radius + gap))
                sy = cy + int(uy * (radius + gap))
                tx = ex - int(ux * (radius + gap))
                ty = ey - int(uy * (radius + gap))
                draw.line([(sx, sy), (tx, ty)], fill=color, width=width)
                # Arrowhead: two short segments rotated ±25° back from the tip.
                head_len = max(8, radius * 2)
                angle = math.atan2(uy, ux)
                for offset in (math.radians(150), math.radians(-150)):
                    hx = tx + int(math.cos(angle + offset) * head_len)
                    hy = ty + int(math.sin(angle + offset) * head_len)
                    draw.line([(tx, ty), (hx, hy)], fill=color, width=width)
                # Hollow end ring, same radius as the start cross's circle so the
                # two endpoints read as a matched pair.
                draw.ellipse(
                    [ex - radius, ey - radius, ex + radius, ey + radius],
                    outline=color, width=width,
                )

    # Full-res output in the configured format (jpeg has no alpha channel, so
    # flatten RGBA → RGB first).
    full_buf = io.BytesIO()
    if cfg.format == "jpeg":
        img.convert("RGB").save(full_buf, format="JPEG", quality=cfg.quality)
    else:
        img.save(full_buf, format="PNG")
    full_bytes = full_buf.getvalue()

    # Thumbnail derived from the same in-memory image — no second decode.
    thumb_img = img if img.mode == "RGB" else img.convert("RGB")
    longest = max(thumb_img.width, thumb_img.height)
    if longest > thumb_max_edge:
        scale = thumb_max_edge / longest
        thumb_img = thumb_img.resize(
            (max(1, round(thumb_img.width * scale)), max(1, round(thumb_img.height * scale)))
        )
    thumb_buf = io.BytesIO()
    thumb_img.save(thumb_buf, format="JPEG", quality=thumb_quality)
    thumb_b64 = "data:image/jpeg;base64," + base64.b64encode(thumb_buf.getvalue()).decode("ascii")

    return full_bytes, thumb_b64
