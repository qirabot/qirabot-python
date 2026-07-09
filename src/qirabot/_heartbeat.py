"""Background heartbeat thread — proves the client process is alive.

The server's orphan cleaner reclaims tasks whose client has gone silent
(no /act step and no heartbeat within the grace period, 5 minutes by
default). Scripts legitimately sleep between bot.ai calls for far longer
than that, so a daemon thread touches ``POST /tasks/{id}/heartbeat`` once
a minute for the lifetime of the Qirabot instance.

Failure policy: a heartbeat must never break the script. Every branch here
degrades — old servers without the endpoint disable the thread for the
session, network blips retry next round, and a terminal task status stops
the thread (the error itself surfaces later, through the /act control
response on the script's next bot call).
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Callable

from qirabot.exceptions import QirabotError

if TYPE_CHECKING:
    from qirabot._transport import Transport

logger = logging.getLogger("qirabot")

# One beat a minute tolerates four straight losses within the server's
# 5-minute grace period.
HEARTBEAT_INTERVAL = 60.0

# Heartbeats are tiny; a hung request should give up long before the
# transport-wide 120s default and just try again next round.
HEARTBEAT_TIMEOUT = 10.0

_TERMINAL_STATUSES = frozenset({"completed", "failed", "timeout", "cancelled"})


class Heartbeat(threading.Thread):
    """Daemon thread beating ``POST /tasks/{task_id}/heartbeat``.

    ``on_terminated`` is called (once, from this thread) when the server
    reports the task is already terminal — the client uses it to flip its
    one-way ``_terminalized`` latch so close() skips the doomed /complete.
    """

    def __init__(
        self,
        transport: Transport,
        task_id: str,
        on_terminated: Callable[[str], None] | None = None,
        interval: float = HEARTBEAT_INTERVAL,
    ):
        super().__init__(name=f"qirabot-heartbeat-{task_id[:8]}", daemon=True)
        self._transport = transport
        self._task_id = task_id
        self._on_terminated = on_terminated
        self._interval = interval
        self._stop_event = threading.Event()
        self._warned_failure = False

    def stop(self) -> None:
        """Wake the thread and wait briefly for it to exit.

        Called from close() before the transport shuts down so no request is
        in flight when the connection pool closes. The join timeout is a
        courtesy — the thread is a daemon, so an abandoned join never blocks
        process exit.
        """
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout=2.0)

    def run(self) -> None:
        # First wait, then beat: the constructor fires right after task
        # creation, which is itself proof of liveness.
        while not self._stop_event.wait(self._interval):
            if not self._beat():
                return

    def _beat(self) -> bool:
        """Send one heartbeat. Returns False when the thread should stop."""
        try:
            result = self._transport.post(
                f"/tasks/{self._task_id}/heartbeat", timeout=HEARTBEAT_TIMEOUT
            )
        except QirabotError as e:
            if e.status_code == 404:
                return self._handle_404(e)
            if not self._warned_failure:
                self._warned_failure = True
                logger.warning(
                    "heartbeat for task %s failed (%s); will keep retrying quietly",
                    self._task_id,
                    e,
                )
            else:
                logger.debug("heartbeat failed for task %s: %s", self._task_id, e)
            return True
        except Exception:
            logger.debug("unexpected heartbeat error for task %s", self._task_id, exc_info=True)
            return True

        self._warned_failure = False
        status = str(result.get("status", ""))
        if status in _TERMINAL_STATUSES:
            logger.warning(
                "task %s was terminated server-side (status=%s); stopping heartbeat",
                self._task_id,
                status,
            )
            if self._on_terminated is not None:
                self._on_terminated(status)
            return False
        return True

    def _handle_404(self, e: QirabotError) -> bool:
        """Distinguish "old server" from "task gone". Both stop the thread.

        A structured ``task.not_found`` code means the server knows the
        endpoint but not the task (deleted, or foreign API key) — treat like
        a terminal status. A 404 with no code is gin's route-level miss: the
        server predates the heartbeat endpoint, so disable for this session
        and fall back to the old rules.
        """
        if e.code == "task.not_found":
            logger.warning(
                "task %s no longer exists on the server; stopping heartbeat", self._task_id
            )
            if self._on_terminated is not None:
                self._on_terminated("")
            return False
        logger.info(
            "server does not support heartbeats (upgrade the server to sleep "
            "beyond the orphan grace period); heartbeat disabled for this run"
        )
        return False
