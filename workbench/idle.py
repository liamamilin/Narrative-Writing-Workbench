"""Idle auto-shutdown: exit the server after a quiet period.

The browser can be closed while the nohup'd server keeps listening; this
watchdog reclaims it. Activity = any HTTP request start (SSE opens count).
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time

log = logging.getLogger("workbench.idle")


class IdleTracker:
    def __init__(self, timeout_seconds: float, shutdown=None):
        self.timeout = float(timeout_seconds)
        self._last = time.monotonic()
        self._lock = threading.Lock()
        self._shutdown = shutdown or (
            lambda: os.kill(os.getpid(), signal.SIGINT))

    def touch(self) -> None:
        with self._lock:
            self._last = time.monotonic()

    def idle_seconds(self) -> float:
        with self._lock:
            return time.monotonic() - self._last

    def check(self) -> bool:
        """True if the idle window elapsed and shutdown was triggered."""
        if self.idle_seconds() < self.timeout:
            return False
        msg = f"空闲 {self.timeout/60:g} 分钟,自动退出。"
        log.info(msg)
        print(msg, flush=True)   # no root logging config in server mode
        self._shutdown()
        return True


def install(app, tracker: IdleTracker, poll_seconds: float | None = None) -> None:
    """Wire the request-touch middleware and the watchdog thread."""
    if poll_seconds is None:
        poll_seconds = max(1.0, min(15.0, tracker.timeout / 4))

    @app.middleware("http")
    async def _touch(request, call_next):
        tracker.touch()
        return await call_next(request)

    def loop():
        while True:
            time.sleep(poll_seconds)
            if tracker.check():
                return

    threading.Thread(target=loop, daemon=True, name="idle-watchdog").start()


def timeout_from_env(default_minutes: float = 30.0) -> float:
    """WORKBENCH_IDLE_TIMEOUT in minutes; 0 or negative disables."""
    raw = os.environ.get("WORKBENCH_IDLE_TIMEOUT", str(default_minutes))
    try:
        return max(float(raw), 0.0) * 60
    except ValueError:
        return default_minutes * 60
