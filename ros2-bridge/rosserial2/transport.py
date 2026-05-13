"""Transport abstraction.

The codec is transport-agnostic. Concrete transports adapt UART, TCP,
or ESP-NOW to a common ``Transport`` interface. The session layer only
talks to this interface.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class TransportError(IOError):
    """Raised on unrecoverable transport-level errors."""


@runtime_checkable
class Transport(Protocol):
    """Minimal transport surface.

    Implementations must be safe to call from a single thread.
    Concurrent reads and writes from one thread each are permitted.
    """

    def read(self, max_bytes: int) -> bytes:
        """Read up to ``max_bytes`` bytes. May return ``b""`` on timeout."""

    def write(self, data: bytes) -> None:
        """Write all bytes. Blocks until the underlying buffer accepts them."""

    def close(self) -> None:
        """Close the transport. Idempotent."""

    @property
    def name(self) -> str:
        """Human-readable label for logs (e.g. ``serial:/dev/ttyUSB0``)."""
