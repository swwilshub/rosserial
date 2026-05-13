"""Pseudoterminal-backed transport.

Used by integration tests: one end is given to the bridge, the other
end is driven by the test as a fake device. Behaves enough like a
real serial port to exercise the full I/O loop.

POSIX-only; the integration tests skip on Windows.
"""

from __future__ import annotations

import contextlib
import errno
import os
import select
import termios
import tty

from rosserial2.transport import Transport, TransportError


def _set_raw(fd: int) -> None:
    """Disable TTY line discipline so we get raw byte I/O.

    Some pty fds reject termios on certain platforms; they're already
    in pass-through mode, so swallow the error.
    """
    with contextlib.suppress(termios.error):
        tty.setraw(fd, termios.TCSANOW)


class PtyTransport(Transport):
    def __init__(self, fd: int, label: str = "pty") -> None:
        self._fd = fd
        self._label = label
        self._closed = False

    @classmethod
    def open_pair(cls) -> tuple[PtyTransport, int]:
        """Open a pty pair. Returns (bridge-side transport, test-side fd).

        Both ends are placed in raw mode so byte I/O is pass-through:
        no line discipline, no echo, no CR/LF translation. The
        test-side fd is a raw file descriptor; tests can use
        ``os.read`` / ``os.write`` on it directly.
        """
        master, slave = os.openpty()
        _set_raw(slave)
        _set_raw(master)
        os.set_blocking(master, False)
        os.set_blocking(slave, False)
        return cls(slave, label=f"pty:slave({slave})"), master

    def read(self, max_bytes: int) -> bytes:
        if self._closed:
            raise TransportError("pty closed")
        r, _, _ = select.select([self._fd], [], [], 0.05)
        if not r:
            return b""
        try:
            data = os.read(self._fd, max_bytes)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                return b""
            raise TransportError(str(exc)) from exc
        if not data:
            raise TransportError("pty EOF")
        return data

    def write(self, data: bytes) -> None:
        if self._closed:
            raise TransportError("pty closed")
        try:
            written = 0
            while written < len(data):
                n = os.write(self._fd, data[written:])
                if n <= 0:
                    raise TransportError("pty short write")
                written += n
        except OSError as exc:
            raise TransportError(str(exc)) from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(OSError):
            os.close(self._fd)

    @property
    def name(self) -> str:
        return self._label
