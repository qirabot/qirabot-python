"""Qirabot SDK client."""

from __future__ import annotations

import atexit
import io
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from qirabot._transport import Transport
from qirabot.adapters import auto
from qirabot.adapters.base import DeviceAdapter, ScreenshotConfig
from qirabot.exceptions import QirabotError, _is_retryable

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
        model_alias: str = "",
        language: str = "",
        task_name: str = "",
        task_id: str = "",
        source: str = "sdk",
        screenshot_dir: str = "",
        screenshot_format: str = "jpeg",
        screenshot_quality: int = 80,
        screenshot_annotate: bool = False,
        retry: int = 1,
        retry_delay: float = 1.0,
    ):
        api_key = api_key or os.environ.get("QIRA_API_KEY", "")
        base_url = base_url or os.environ.get("QIRA_BASE_URL", "https://app.qirabot.com")
        self._transport = Transport(base_url=base_url, api_key=api_key, timeout=timeout)
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
        self._screenshot_dir = screenshot_dir or os.environ.get("QIRA_SCREENSHOT_DIR", "")
        self._screenshot_counter = 0
        self._screenshot_config = ScreenshotConfig(
            format=screenshot_format,
            quality=screenshot_quality,
            annotate=screenshot_annotate,
        )
        self._retry = retry
        self._retry_delay = retry_delay
        self._step_seq = 0
        atexit.register(self.close)

    @property
    def task_id(self) -> str | None:
        return self._task_id


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
        from playwright.sync_api import sync_playwright

        if cdp_url and (user_data_dir or channel or args or headless):
            raise ValueError(
                "cdp_url cannot be combined with headless/user_data_dir/channel/args "
                "(those apply only when launching a browser)"
            )

        pw = sync_playwright().start()
        self._pw_instances.append(pw)

        viewport_dict = {"width": viewport[0], "height": viewport[1]}

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

    def click(
        self,
        target: Any,
        locate: str,
        *,
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> Any:
        """AI-powered click: locate element by description and click it.

        Returns the current target (the same kind you passed in: a Playwright
        Page, Selenium/Appium driver, or the pyautogui module). If the click
        opened a link in a new tab, this is that new tab — reassign it
        (``page = bot.click(page, ...)``) to keep operating on the active page.
        """
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
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> Any:
        """AI-powered type: locate input field and type text.

        Returns the current target (same kind you passed in); reassign it
        (``page = bot.type_text(page, ...)``) to follow any tab switch.
        """
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
        retry: int | None = None,
        model_alias: str = "",
        language: str = "",
    ) -> Any:
        """AI-powered double-click: locate element by description and double-click it.

        Returns the current target (same kind you passed in); reassign it
        (``page = bot.double_click(page, ...)``) to follow any tab switch.
        """
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
    ) -> bool:
        """Wait until a visual condition is met. Returns True if met within timeout."""
        import time
        deadline = time.monotonic() + timeout
        while True:
            met = self.verify(target, assertion, model_alias=model_alias, language=language)
            if met:
                return True
            if time.monotonic() >= deadline:
                return False
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
        """AI-powered multi-step operation."""

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

            result = self._transport.post_multipart(
                f"/tasks/{self._task_id}/act",
                files=files,
                data={"request": json.dumps(request_body)},
            )

            if not result.get("success"):
                error_msg = result.get("error", "AI request failed")
                if result.get("finished"):
                    logger.error("failed: %s", error_msg)
                    return RunResult(success=False, output=error_msg, steps=steps)
                raise QirabotError(error_msg)

            action_type = result.get("actionType")
            action_params = result.get("params") or {}
            finished = result.get("finished", False)
            decision = result.get("decision", "")

            coords = _extract_coords(action_params)
            if screenshot_bytes:
                self._save_screenshot(screenshot_bytes, action_type or "ai", coords)

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
                logger.info("completed: %s", output)
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
        """Take a screenshot and save it to ``screenshot_dir``.

        Returns the saved file path, or ``None`` if no ``screenshot_dir`` is
        configured. No AI, no billing.
        """
        adapter = self._get_adapter(target)
        data = adapter.screenshot(self._screenshot_config)
        return self._save_screenshot(data, "manual")

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

    def _save_screenshot(self, data: bytes, label: str, coords: tuple[float, float] | None = None) -> Path | None:
        if not self._screenshot_dir:
            return None
        dir_path = Path(self._screenshot_dir)
        if self._task_id:
            dir_path = dir_path / self._task_id
        dir_path.mkdir(parents=True, exist_ok=True)
        self._screenshot_counter += 1

        if coords is not None and self._screenshot_config.annotate:
            data = _annotate_screenshot(data, coords[0], coords[1])
            label = f"{label}_x{int(coords[0])}_y{int(coords[1])}"

        filename = f"{self._screenshot_counter:03d}_{label}.{self._screenshot_config.extension}"
        path = dir_path / filename
        path.write_bytes(data)
        logger.debug("screenshot saved: %s", path)
        return path

    def current_page(self, target: Any) -> Any:
        """Return the actual current page/target (may differ from the original after tab switches)."""
        return self._result(self._get_adapter(target))

    def _get_adapter(self, target: Any) -> DeviceAdapter:
        key = id(target)
        adapter = self._adapters.get(key)
        if adapter is None:
            adapter = auto.detect(target)
            self._adapters[key] = adapter
        return adapter

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
        self._adapters[id(target)] = adapter
        return target

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
            raise QirabotError(result.get("error", "AI request failed"))

        coords = _extract_coords(result.get("params"))
        self._save_screenshot(screenshot_bytes, action.get("type", "action"), coords)

        if execute_result and result.get("actionType"):
            self._execute_action(adapter, result)

        return result

    def _execute_action(self, adapter: DeviceAdapter, resp_action: dict[str, Any]) -> None:
        action_type = resp_action.get("actionType", "")
        params = resp_action.get("params", {})
        adapter.execute(action_type, params)

    def fail(self, error_message: str = "") -> None:
        """Report a client-side failure so the task is recorded as failed.

        Use this when the run is aborted by an error on the client (e.g. the CLI
        catches an exception): without it, the default close() would complete the
        still-running task as succeeded. Idempotent and a no-op for externally
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

    def close(self) -> None:
        """Clean up all resources."""
        if self._closed:
            return
        self._closed = True
        # Only auto-complete (as success) when no terminal status was reported
        # yet — an errored run reports failure via fail() first.
        if self._task_id is not None and not self._external_task and not self._terminalized:
            self._terminalized = True
            try:
                self._transport.post(f"/tasks/{self._task_id}/complete")
            except Exception:
                logger.debug("failed to complete task %s on close", self._task_id)
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
        # (Ctrl+C) is a deliberate cancel, not a failure — mirror the CLI.
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


def _annotate_screenshot(data: bytes, x: float, y: float) -> bytes:
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

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
