"""Qirabot SDK client."""

from __future__ import annotations

import atexit
import io
import json
import logging
import os
import time
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from qirabot._optional import require
from qirabot._transport import Transport
from qirabot.adapters import auto
from qirabot.adapters.base import DeviceAdapter, ScreenshotConfig
from qirabot.exceptions import (
    ActionError,
    QirabotError,
    QirabotTimeoutError,
    _is_retryable,
)

if TYPE_CHECKING:
    from playwright.sync_api import ViewportSize

logger = logging.getLogger("qirabot")


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
class RunResult:
    """Result of bot.ai() multi-step operation."""

    success: bool
    output: str = ""
    steps: list[StepResult] = field(default_factory=list)


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
    ):
        api_key = api_key or os.environ.get("QIRA_API_KEY", "")
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
        # ai() instruction -> success, for per-section PASS/FAIL in the report.
        self._section_outcomes: dict[str, bool] = {}
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
        atexit.register(self.close)

    @property
    def report_dir(self) -> str:
        """The per-run output directory (report.html + screenshots/ + recording).

        Drop a file named ``recording.mp4`` or ``recording.webm`` here and the
        report embeds it automatically. Use an external screen recorder, e.g.
        ``dev.start_recording(output=os.path.join(bot.report_dir, "recording.mp4"))``,
        or Playwright's native recording: create your own context with
        ``record_video_dir=bot.report_dir``, wrap its page with the bot, and on
        ``page.context.close()`` rename the emitted ``.webm`` to
        ``recording.webm``.
        """
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
            headless: run without a visible window.
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

    def extract(
        self,
        target: Any,
        instruction: str,
        *,
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> str:
        """Extract data from the screen using AI. Returns extracted text."""
        result = self._ai_action(
            target,
            action={"type": "extract", "params": {"instruction": instruction}},
            model_alias=model_alias,
            language=language,
            execute_result=False,
            retry=retry,
        )
        return str(result.get("output", ""))

    def verify(
        self,
        target: Any,
        assertion: str,
        *,
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> bool:
        """Verify a visual assertion. Returns True if the assertion holds."""
        result = self._ai_action(
            target,
            action={"type": "assert", "params": {"assertion": assertion}},
            model_alias=model_alias,
            language=language,
            execute_result=False,
            retry=retry,
        )
        return bool(result.get("finished", False))

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
    ) -> RunResult:
        """AI-powered multi-step operation.

        Steps run by this call are grouped under ``instruction`` in the report.
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
            )
            self._section_outcomes[self._current_section] = result.success
            return result
        except Exception:
            self._section_outcomes[self._current_section] = False
            raise
        finally:
            self._current_section = prev_section

    def _ai_loop(
        self,
        target: Any,
        instruction: str,
        max_steps: int = 20,
        *,
        on_step: Callable[[StepResult], None] | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> RunResult:
        adapter = self._get_adapter(target)
        steps: list[StepResult] = []
        last_action_result = ""
        last_was_save_note = False

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
                request_body["action"] = {
                    "type": "ai",
                    "params": {"instruction": instruction, "max_steps": max_steps},
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

            if not result.get("success"):
                error_msg = result.get("error", "AI request failed")
                if result.get("finished"):
                    logger.error("failed: %s", error_msg)
                    return RunResult(success=False, output=error_msg, steps=steps)
                raise ActionError(error_msg)

            action_type = result.get("actionType")
            action_params = result.get("params") or {}
            finished = result.get("finished", False)
            decision = result.get("decision", "")

            coords = _extract_coords(action_params)
            self._record_step(
                screenshot_bytes,
                action_type or "ai",
                action_params,
                coords,
                output=result.get("output", ""),
                finished=finished,
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

            if on_step:
                on_step(step_result)

            if finished:
                output = result.get("output", "")
                # Log a short completion marker, not the full output: the result
                # text is the caller's to surface via result.output, and dumping
                # it here duplicates that for any caller that prints the result
                # (and is out of step with the short per-step progress lines).
                logger.info("completed in %d step(s)", len(steps))
                return RunResult(
                    success=True,
                    output=output,
                    steps=steps,
                )

            if action_type and action_type != "done":
                try:
                    self._execute_action(adapter, result)
                    last_action_result = "ok"
                except Exception as e:
                    last_action_result = f"ERROR: {e}"

            last_was_save_note = action_type == "save_note"

        logger.error("failed: max steps (%d) reached", max_steps)
        return RunResult(success=False, output="max steps reached", steps=steps)

    def screenshot(self, target: Any) -> Path | None:
        """Take a screenshot and save it to ``report_dir/screenshots/``.

        Returns the saved file path, or ``None`` when ``report=False``. No AI,
        no billing.
        """
        adapter = self._get_adapter(target)
        data = adapter.screenshot(self._screenshot_config)
        return self._save_frame(data, "manual")

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

    def _record_step(
        self,
        data: bytes,
        action_type: str,
        params: dict[str, Any] | None,
        coords: tuple[float, float] | None = None,
        *,
        output: str = "",
        finished: bool = False,
        success: bool = True,
    ) -> None:
        """Save the screenshot (if reporting) and append a step to the timeline.

        ``assert`` actions (verify / wait_for polls) are control-flow, not visual
        steps, so they are skipped — otherwise an auto-wait would spam the report
        and disk with a dozen identical poll frames.
        """
        # Reporting off → zero overhead. ``assert`` actions (verify / wait_for
        # polls) are control-flow, not visual steps, so they are skipped too —
        # otherwise an auto-wait would spam the report and disk with poll frames.
        if not self._report or action_type == "assert":
            return
        # Annotation and thumbnailing decode the image with PIL; never let a
        # malformed/unexpected screenshot break the actual action — degrade to
        # the raw bytes / no thumbnail instead.
        annotated = data
        if data and coords is not None and self._screenshot_config.annotate:
            try:
                annotated = _annotate_screenshot(
                    data, coords[0], coords[1], self._screenshot_config
                )
            except Exception:
                logger.debug("annotate failed", exc_info=True)
        frame = self._save_frame(annotated, action_type or "action") if data else None
        thumb = ""
        if data:
            try:
                thumb = _thumbnail_b64(annotated)
            except Exception:
                logger.debug("thumbnail failed", exc_info=True)
        self._log.append(
            {
                "section": self._current_section,
                "action_type": action_type or "",
                "params": params or {},
                "output": output or "",
                "finished": bool(finished),
                "success": bool(success),
                "coords": list(coords) if coords else None,
                # relative to report_dir so the html can link it directly
                "screenshot": f"screenshots/{frame.name}" if frame else "",
                "thumb": thumb,
            }
        )

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

        if not result.get("success"):
            raise ActionError(result.get("error", "AI request failed"))

        coords = _extract_coords(result.get("params"))
        self._record_step(
            screenshot_bytes,
            result.get("actionType") or action.get("type", "action"),
            result.get("params") or action.get("params") or {},
            coords,
            output=result.get("output", ""),
            finished=result.get("finished", False),
            success=result.get("success", True),
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
        script catches an exception): without it, the default close() would
        complete the still-running task as succeeded. Idempotent and a no-op for externally
        owned tasks. The server's state machine rejects a later success-complete
        once the task is failed, so a subsequent close() cannot override it.
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
        recorded as cancelled rather than failed or, worse, succeeded.

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
        # Embed a screen recording if one was dropped into report_dir. We accept
        # .mp4 (external recorders) and .webm (Playwright's native recording —
        # point its record_video_dir at report_dir); first match wins.
        recording = ""
        for name in ("recording.mp4", "recording.webm"):
            if (self._report_dir / name).exists():
                recording = name
                break
        try:
            _report.write_html(
                self._log,
                out,
                title=self._task_name or "",
                task_id=self._task_id or "",
                outcomes=self._section_outcomes,
                recording=recording,
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
        # Emit the run report before tearing down (best-effort; never block
        # cleanup). Runs on normal exit, exception (via __exit__), and atexit.
        self._write_report()
        # Only auto-complete (as success) when no terminal status was reported
        # yet — an errored run reports failure via fail() first.
        if self._task_id is not None and not self._external_task and not self._terminalized:
            self._terminalized = True
            try:
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


def _extract_coords(params: dict[str, Any] | None) -> tuple[float, float] | None:
    if not params:
        return None
    x = params.get("x")
    y = params.get("y")
    if x is not None and y is not None:
        return (float(x), float(y))
    return None


def _annotate_screenshot(
    data: bytes, x: float, y: float, config: ScreenshotConfig | None = None
) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.open(io.BytesIO(data)).convert("RGBA")
    draw = ImageDraw.Draw(img)
    color = (255, 0, 0, 255)

    short_side = min(img.width, img.height)
    radius = max(4, round(short_side * 0.015))
    line_len = int(radius * 1.5)
    width = 3 if short_side > 2000 else 2
    gap = radius + 2
    cx, cy = int(x), int(y)

    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        outline=color, width=width,
    )
    draw.line([(cx - gap - line_len, cy), (cx - gap, cy)], fill=color, width=width)
    draw.line([(cx + gap, cy), (cx + gap + line_len, cy)], fill=color, width=width)
    draw.line([(cx, cy - gap - line_len), (cx, cy - gap)], fill=color, width=width)
    draw.line([(cx, cy + gap), (cx, cy + gap + line_len)], fill=color, width=width)

    # Re-encode in the configured format so the bytes match the filename
    # extension (jpeg has no alpha channel, so flatten RGBA → RGB first).
    cfg = config or ScreenshotConfig()
    buf = io.BytesIO()
    if cfg.format == "jpeg":
        img.convert("RGB").save(buf, format="JPEG", quality=cfg.quality)
    else:
        img.save(buf, format="PNG")
    return buf.getvalue()


def _thumbnail_b64(data: bytes, max_edge: int = 800, quality: int = 60) -> str:
    """Downscale screenshot bytes to a compact base64 data URI for the report.

    Keeps reports self-contained (and bounds memory) regardless of whether
    full-resolution frames are kept on disk.
    """
    import base64

    from PIL import Image

    img = Image.open(io.BytesIO(data)).convert("RGB")
    longest = max(img.width, img.height)
    if longest > max_edge:
        scale = max_edge / longest
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class _BoundQirabot:
    """A :class:`Qirabot` proxy with a target pre-bound (see ``Qirabot.bind``).

    Action methods drop the leading ``target`` argument; everything else
    (lifecycle, context manager, unknown attributes) delegates to the wrapped
    ``Qirabot``. Methods that return the current target (tab-following) update
    the bound target in place, so the proxy keeps following the active page on
    Playwright while staying a no-op on single-target frameworks.
    """

    def __init__(self, bot: Qirabot, target: Any) -> None:
        self._bot = bot
        self._target = target

    @property
    def bot(self) -> Qirabot:
        """The underlying :class:`Qirabot` (rarely needed)."""
        return self._bot

    def _rebind(self, result: Any) -> Any:
        # Follow tab/window switches: the action's return value is the current
        # target, which may differ from the one we sent (Playwright new tab).
        self._target = result
        return result

    # -- action methods: inject the bound target ---------------------------

    def click(
        self,
        locate: str,
        *,
        timeout: float = 0.0,
        interval: float = 2.0,
        wait: str = "",
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> Any:
        return self._rebind(
            self._bot.click(
                self._target,
                locate,
                timeout=timeout,
                interval=interval,
                wait=wait,
                retry=retry,
                model_alias=model_alias,
                language=language,
            )
        )

    def type_text(
        self,
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
        return self._rebind(
            self._bot.type_text(
                self._target,
                locate,
                text,
                press_enter=press_enter,
                clear_before_typing=clear_before_typing,
                timeout=timeout,
                interval=interval,
                wait=wait,
                retry=retry,
                model_alias=model_alias,
                language=language,
            )
        )

    def double_click(
        self,
        locate: str,
        *,
        timeout: float = 0.0,
        interval: float = 2.0,
        wait: str = "",
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> Any:
        return self._rebind(
            self._bot.double_click(
                self._target,
                locate,
                timeout=timeout,
                interval=interval,
                wait=wait,
                retry=retry,
                model_alias=model_alias,
                language=language,
            )
        )

    def extract(
        self,
        instruction: str,
        *,
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> str:
        return self._bot.extract(
            self._target, instruction, retry=retry, model_alias=model_alias, language=language
        )

    def verify(
        self,
        assertion: str,
        *,
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> bool:
        return self._bot.verify(
            self._target, assertion, retry=retry, model_alias=model_alias, language=language
        )

    def wait_for(
        self,
        assertion: str,
        timeout: float = 30.0,
        interval: float = 2.0,
        *,
        model_alias: str = "",
        language: str = "",
    ) -> "_BoundQirabot":
        """Wait until ``assertion`` holds, else raise :class:`QirabotTimeoutError`.

        Returns the bound handle (unchanged target) so calls can be chained, e.g.
        ``bot.wait_for("公告出现").click("关闭公告")``.
        """
        self._bot.wait_for(
            self._target,
            assertion,
            timeout,
            interval,
            model_alias=model_alias,
            language=language,
        )
        return self

    def ai(
        self,
        instruction: str,
        max_steps: int = 20,
        *,
        on_step: Callable[[StepResult], None] | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> RunResult:
        return self._bot.ai(
            self._target,
            instruction,
            max_steps,
            on_step=on_step,
            model_alias=model_alias,
            language=language,
        )

    def screenshot(self) -> Path | None:
        return self._bot.screenshot(self._target)

    def go_back(self) -> Any:
        return self._rebind(self._bot.go_back(self._target))

    def close_tab(self) -> Any:
        return self._rebind(self._bot.close_tab(self._target))

    def navigate(self, url: str) -> Any:
        return self._rebind(self._bot.navigate(self._target, url))

    def scroll(
        self,
        direction: str = "down",
        distance: int = 3,
        *,
        x: float | None = None,
        y: float | None = None,
    ) -> None:
        self._bot.scroll(self._target, direction, distance, x=x, y=y)

    def current_page(self) -> Any:
        """The live current target (always fresh — use for native interop)."""
        return self._rebind(self._bot.current_page(self._target))

    # -- high-frequency lifecycle: explicit for typing/IDE -----------------

    def close(self) -> None:
        self._bot.close()

    def open(self, *args: Any, **kwargs: Any) -> Any:
        return self._bot.open(*args, **kwargs)

    @property
    def task_id(self) -> str | None:
        return self._bot.task_id

    # -- everything else (launch_app/fail/cancel/…) delegates --------------

    def __getattr__(self, name: str) -> Any:
        # __getattr__ runs only when normal lookup fails; guard _bot to avoid
        # recursion before __init__ has set it.
        if name == "_bot":
            raise AttributeError(name)
        return getattr(self._bot, name)

    def __enter__(self) -> _BoundQirabot:
        self._bot.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self._bot.__exit__(exc_type, exc_val, exc_tb)
