"""Reconnecting transport wrapper.

Wraps any ``Transport`` factory in a supervisor that reopens the
underlying connection on failure, with capped exponential backoff.
The bridge loop sees a single ``Transport`` whose ``read()`` may
raise ``TransportError`` once per drop; on the next call the wrapper
will already be retrying.

See ADR-0008.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable

from rosserial2.transport import Transport, TransportError

logger = logging.getLogger("rosserial2.reconnect")


class ReconnectingTransport(Transport):
    """Lazy + self-healing transport.

    Parameters
    ----------
    open_fn:
        Factory that produces a fresh underlying ``Transport``. Called
        on first use and on every reopen.
    label:
        Human-readable label, exposed via ``.name``.
    initial_backoff_s, max_backoff_s:
        Backoff bounds for reopen attempts.
    sleep:
        Sleep function; tests inject a fake to skip wall-clock waits.
    """

    def __init__(
        self,
        open_fn: Callable[[], Transport],
        label: str = "reconnecting",
        initial_backoff_s: float = 0.5,
        max_backoff_s: float = 8.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._open_fn = open_fn
        self._label = label
        self._initial = initial_backoff_s
        self._max = max_backoff_s
        self._sleep = sleep
        self._inner: Transport | None = None
        self._backoff = initial_backoff_s
        self._closed = False
        # Telemetry.
        self.reopen_attempts: int = 0
        self.reopen_failures: int = 0

    @property
    def name(self) -> str:
        if self._inner is not None:
            return f"{self._label}({self._inner.name})"
        return f"{self._label}(closed)"

    def close(self) -> None:
        self._closed = True
        self._close_inner()

    def read(self, max_bytes: int) -> bytes:
        if self._closed:
            raise TransportError("transport closed")
        if self._inner is None:
            self._reopen()
        try:
            return self._inner.read(max_bytes)  # type: ignore[union-attr]
        except TransportError:
            self._close_inner()
            raise

    def write(self, data: bytes) -> None:
        if self._closed:
            raise TransportError("transport closed")
        if self._inner is None:
            self._reopen()
        try:
            self._inner.write(data)  # type: ignore[union-attr]
        except TransportError:
            self._close_inner()
            raise

    # --- internals ---------------------------------------------------

    def _close_inner(self) -> None:
        if self._inner is None:
            return
        with contextlib.suppress(Exception):
            self._inner.close()
        self._inner = None

    def _reopen(self) -> None:
        """Try to (re)open the inner transport. May sleep on failure."""
        while not self._closed:
            self.reopen_attempts += 1
            try:
                self._inner = self._open_fn()
                self._backoff = self._initial
                logger.info("%s: opened underlying transport", self._label)
                return
            except TransportError as exc:
                self.reopen_failures += 1
                wait = self._backoff
                self._backoff = min(self._backoff * 2.0, self._max)
                logger.warning(
                    "%s: reopen failed (%s); sleeping %.2fs before retry",
                    self._label, exc, wait,
                )
                self._sleep(wait)
        raise TransportError("transport closed during reopen")
