"""On-screen task progress overlay, excluded from the bot's own screenshots.

The window lives in a helper process (see _overlay_helper.py for why), so
this module is pure plumbing: spawn the helper, feed it one JSON line per
update, and degrade to a no-op on any failure — a progress display must
never be able to break the run it is displaying.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from typing import Any, Callable

logger = logging.getLogger("qirabot")

# Keep the text within what the fixed-size helper window can show.
_MAX_LINE = 60


def _clip(text: str, limit: int = _MAX_LINE) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _format_step(step: Any) -> str:
    """Two lines: what the bot is doing, then why (the model's decision)."""
    params = getattr(step, "params", None) or {}
    head_parts = [f"step {step.step}", step.action_type or "…"]
    if "locate" in params:
        head_parts.append(f'"{params["locate"]}"')
    if "text" in params:
        head_parts.append(f'← "{params["text"]}"')
    if "direction" in params:
        head_parts.append(
            f"{params['direction']} {params.get('amount', '')}".rstrip()
        )
    lines = [_clip(" · ".join(str(p) for p in head_parts))]
    decision = getattr(step, "decision", "")
    if decision:
        lines.append(_clip(decision))
    return "\n".join(lines)


class Overlay:
    """Small always-on-top progress window in the screen's bottom-right corner.

    The window is excluded from screen capture (macOS ``NSWindowSharingNone``,
    Windows ``WDA_EXCLUDEFROMCAPTURE``), click-through, and never focused, so
    it is invisible to bot screenshots and inert to bot input. Unsupported
    platforms and every runtime failure degrade to a silent no-op.

    Usage — standalone::

        with qirabot.Overlay() as ov:
            bot.ai(target, "...", on_step=ov.step)

    or let the client drive it: ``Qirabot(overlay=True)``.
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen[bytes] | None = None
        self._failed = False

    @staticmethod
    def supported() -> bool:
        return sys.platform in ("darwin", "win32")

    def start(self) -> None:
        """Spawn the helper window process. Idempotent; safe to skip — every
        send calls it lazily."""
        if self._proc is not None or self._failed:
            return
        if not self.supported():
            self._failed = True
            logger.debug("overlay: unsupported platform %s", sys.platform)
            return
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "qirabot._overlay_helper"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            self._failed = True
            logger.debug("overlay: helper failed to start", exc_info=True)

    def _send(self, obj: dict[str, Any]) -> None:
        self.start()
        proc = self._proc
        if proc is None or proc.stdin is None:
            return
        try:
            proc.stdin.write(
                (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
            )
            proc.stdin.flush()
        except Exception:
            # Helper died (e.g. exit 3 on a missing GUI dep): stop trying.
            self._failed = True
            self._proc = None
            logger.debug("overlay: helper write failed", exc_info=True)

    def set_text(self, text: str) -> None:
        """Replace the window text (multi-line ok, keep it short)."""
        self._send({"text": text})

    def step(self, step: Any) -> None:
        """``on_step``-compatible: render a StepResult into the window."""
        self.set_text(_format_step(step))

    def wrap(
        self, on_step: Callable[[Any], None] | None
    ) -> Callable[[Any], None]:
        """Chain the overlay in front of a user ``on_step`` callback."""
        if on_step is None:
            return self.step

        def chained(step_result: Any) -> None:
            self.step(step_result)
            on_step(step_result)

        return chained

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.write(b'{"cmd": "close"}\n')
                proc.stdin.flush()
                proc.stdin.close()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def __enter__(self) -> Overlay:
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
