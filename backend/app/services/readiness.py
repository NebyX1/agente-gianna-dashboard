"""Bound dependency probes without abandoning or multiplying blocked native calls."""

from concurrent.futures import Future, TimeoutError
from threading import Lock, Thread
from typing import Callable


class ReadinessProbe:
    def __init__(self, check: Callable[[], bool], timeout: float = 3):
        self.check = check
        self.timeout = timeout
        self._lock = Lock()
        self._pending: Future | None = None

    def _run(self, future: Future):
        try:
            result = bool(self.check())
        except Exception:
            result = False
        future.set_result(result)

    def ready(self) -> bool:
        with self._lock:
            if self._pending is None or self._pending.done():
                self._pending = Future()
                Thread(target=self._run, args=(self._pending,), daemon=True).start()
            future = self._pending
        try:
            return future.result(timeout=self.timeout)
        except TimeoutError:
            # The native operation still owns its connection. Keep its single slot
            # until it finishes rather than spawning another blocked probe.
            return False
