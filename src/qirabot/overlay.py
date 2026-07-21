"""On-screen task progress overlay, excluded from the bot's own screenshots.

The window lives in a helper process (see _overlay_helper.py for why), so
this module is pure plumbing: spawn the helper, feed it one JSON line per
update, and degrade to a no-op on any failure — a progress display must
never be able to break the run it is displaying.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from typing import Any, Callable

logger = logging.getLogger("qirabot")

# Character budgets, sized to the fixed helper window. Instructions, locate
# descriptions, typed text, and model decisions are all unbounded user/model
# content — every field is clipped on its own before composing, so one long
# field can never crowd out the others, and the composed line is clipped
# again so the pipe message stays bounded no matter what. The helper's
# labels truncate visually on top of this (CJK glyphs are wider per char
# than these budgets assume).
_TITLE_MAX = 80  # headline: the running instruction
_HEAD_MAX = 70  # body line 1: step counter + action + params
_LOCATE_MAX = 40  # the "locate" param inside the head line
_TYPED_MAX = 30  # the "text" param inside the head line
_BODY_MAX = 160  # body lines 2-3: the model's decision / final outcome


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _format_step(step: Any, total: int | None = None) -> str:
    """Body text: what the bot is doing, then why (the model's decision)."""
    params = getattr(step, "params", None) or {}
    counter = f"step {step.step}" + (f"/{total}" if total else "")
    head_parts = [counter, step.action_type or "…"]
    if "locate" in params:
        head_parts.append(f'"{_clip(str(params["locate"]), _LOCATE_MAX)}"')
    if "text" in params:
        head_parts.append(f'← "{_clip(str(params["text"]), _TYPED_MAX)}"')
    if "direction" in params:
        head_parts.append(
            f"{params['direction']} {params.get('amount', '')}".rstrip()
        )
    lines = [_clip(" · ".join(str(p) for p in head_parts), _HEAD_MAX)]
    decision = getattr(step, "decision", "")
    if decision:
        # The body is three text lines tall: one for the action head, two
        # for the decision (it word-wraps inside the label).
        lines.append(_clip(str(decision), _BODY_MAX))
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
            # QIRA_OVERLAY_DEBUG=1 lets the helper's stderr through, to
            # diagnose why the window doesn't appear (missing pyobjc, etc.).
            debug = os.environ.get("QIRA_OVERLAY_DEBUG", "") not in ("", "0")
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "qirabot._overlay_helper"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=None if debug else subprocess.DEVNULL,
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
            # ensure_ascii (the default) keeps the wire pure ASCII: the
            # helper's stdin decoding can then never corrupt CJK text, no
            # matter the locale (Windows pipes default to GBK/cp936 etc.).
            proc.stdin.write((json.dumps(obj) + "\n").encode("ascii"))
            proc.stdin.flush()
        except Exception:
            # Helper died (e.g. exit 3 on a missing GUI dep): stop trying.
            self._failed = True
            self._proc = None
            # Close the pipe under our own guard — a buffered writer left
            # open would flush again at interpreter shutdown and print an
            # unhandled "Exception ignored" BrokenPipeError traceback.
            try:
                proc.stdin.close()
            except Exception:
                pass
            logger.debug("overlay: helper write failed", exc_info=True)

    def set_text(self, text: str) -> None:
        """Replace the window's body text (multi-line ok, keep it short)."""
        self._send({"text": text})

    def begin(self, instruction: str, edge_glow: bool = False) -> None:
        """Start of a run: headline the instruction, show the amber running
        dot, and (re)start the elapsed clock. Clears leftover body text.

        ``edge_glow=True`` additionally lights a slow-breathing glow along
        the screen edges — the "machine is being controlled, hands off"
        signal. Only pass it when the run drives the REAL mouse/keyboard
        (desktop backends); remote-protocol runs would send a false signal.
        The glow is capture-excluded like the window, and on platforms where
        exclusion isn't available it simply never shows (a glowing frame in
        every screenshot would blind the bot).
        """
        self._send(
            {
                "title": _clip(str(instruction), _TITLE_MAX),
                "state": "run",
                "text": "",
                "edge": bool(edge_glow),
            }
        )

    def step(self, step: Any, total: int | None = None) -> None:
        """``on_step``-compatible: render a StepResult into the window.
        ``total`` adds the max-steps denominator ("step 3/20")."""
        self.set_text(_format_step(step, total))

    def finish(self, success: bool, message: str = "") -> None:
        """Show the run's final outcome (✓/✗ glyph, frozen clock); stays up
        until close(). Always turns the edge glow off — control has ended."""
        payload: dict[str, Any] = {"state": "ok" if success else "fail", "edge": False}
        message = _clip(str(message), _BODY_MAX)
        if message:
            payload["text"] = message
        self._send(payload)

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

    def close(self, linger: float = 0.0) -> None:
        """Tear the window down; ``linger`` keeps it up that many seconds
        first, so a final finish() text is readable before it vanishes."""
        proc, self._proc = self._proc, None
        if proc is None:
            return
        if proc.stdin is not None:
            try:
                proc.stdin.write(
                    (json.dumps({"cmd": "close", "linger": linger}) + "\n").encode()
                )
                proc.stdin.flush()
            except Exception:
                pass
            finally:
                # Always close, even after a failed write: an open buffered
                # writer re-flushes at interpreter shutdown and prints an
                # "Exception ignored" BrokenPipeError traceback.
                try:
                    proc.stdin.close()
                except Exception:
                    pass
        try:
            proc.wait(timeout=linger + 2)
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
