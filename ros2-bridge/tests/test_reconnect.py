"""Reconnecting-transport supervisor tests.

Uses an in-memory fake transport so the test can choose exactly when
opens succeed and fail.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from rosserial2.reconnect import ReconnectingTransport
from rosserial2.transport import Transport, TransportError


@dataclass
class _FakeTransport(Transport):
    incoming: bytes = b""
    outgoing: bytearray = field(default_factory=bytearray)
    fail_read_after: int | None = None
    fail_write_after: int | None = None
    reads: int = 0
    writes: int = 0
    closed: bool = False

    @property
    def name(self) -> str:
        return "fake"

    def read(self, max_bytes: int) -> bytes:
        if self.closed:
            raise TransportError("closed")
        self.reads += 1
        if self.fail_read_after is not None and self.reads > self.fail_read_after:
            raise TransportError("boom-read")
        chunk = self.incoming[:max_bytes]
        self.incoming = self.incoming[max_bytes:]
        return chunk

    def write(self, data: bytes) -> None:
        if self.closed:
            raise TransportError("closed")
        self.writes += 1
        if self.fail_write_after is not None and self.writes > self.fail_write_after:
            raise TransportError("boom-write")
        self.outgoing.extend(data)

    def close(self) -> None:
        self.closed = True


def test_reopens_after_a_read_error() -> None:
    instances: list[_FakeTransport] = []

    def factory() -> _FakeTransport:
        t = _FakeTransport(incoming=b"abc", fail_read_after=1)
        instances.append(t)
        return t

    sleeps: list[float] = []
    rt = ReconnectingTransport(open_fn=factory, sleep=sleeps.append)
    try:
        assert rt.read(16) == b"abc"
        # Next read returns "" because incoming is exhausted then fails.
        # Wait — first read of the second underlying read raises.
        with pytest.raises(TransportError):
            rt.read(16)
        # Inner has been closed. The next read reopens.
        assert rt.read(16) == b"abc"
        assert len(instances) == 2
        # Successful reopen resets the backoff: sleeps were empty.
        assert sleeps == []
    finally:
        rt.close()


def test_reopen_backoff_caps_at_max() -> None:
    attempts: list[int] = [0]

    def factory() -> _FakeTransport:
        attempts[0] += 1
        if attempts[0] < 4:
            raise TransportError(f"fail #{attempts[0]}")
        return _FakeTransport(incoming=b"ok")

    sleeps: list[float] = []
    rt = ReconnectingTransport(
        open_fn=factory,
        initial_backoff_s=0.1,
        max_backoff_s=0.3,
        sleep=sleeps.append,
    )
    try:
        assert rt.read(16) == b"ok"
        # First three opens fail and sleep; the fourth succeeds.
        # Expected sleeps: 0.1, 0.2, 0.3 (capped).
        assert sleeps == [0.1, 0.2, 0.3]
        assert rt.reopen_attempts == 4
        assert rt.reopen_failures == 3
    finally:
        rt.close()


def test_write_error_triggers_reopen() -> None:
    seq: list[_FakeTransport] = []

    def factory() -> _FakeTransport:
        t = _FakeTransport(fail_write_after=0)  # any write fails
        seq.append(t)
        return t

    rt = ReconnectingTransport(open_fn=factory, sleep=lambda s: None)
    try:
        with pytest.raises(TransportError):
            rt.write(b"hi")
        assert seq[0].closed  # first transport was torn down
        # Now the next write would reopen and try again, then fail again.
        with pytest.raises(TransportError):
            rt.write(b"hi")
        assert len(seq) == 2
    finally:
        rt.close()


def test_close_stops_attempting_to_reopen() -> None:
    def factory() -> _FakeTransport:
        raise TransportError("never")

    sleeps: list[float] = []
    rt = ReconnectingTransport(
        open_fn=factory,
        initial_backoff_s=0.01,
        max_backoff_s=0.01,
        sleep=lambda s: (sleeps.append(s), rt.close())[0],  # close after 1 sleep
    )
    with pytest.raises(TransportError):
        rt.read(1)
    assert len(sleeps) == 1
