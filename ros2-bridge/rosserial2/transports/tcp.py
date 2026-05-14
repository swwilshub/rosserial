"""TCP server transport.

The bridge binds and listens. The device (typically over WiFi) opens
a TCP connection. Single client at a time — connecting again displaces
the previous client, which surfaces as a ``TransportError`` on the
bridge's next read.

The accept step blocks up to ``accept_timeout_s`` so the bridge loop
stays responsive.
"""

from __future__ import annotations

import contextlib
import logging
import select
import socket

from rosserial2.transport import Transport, TransportError

logger = logging.getLogger("rosserial2.tcp")


class TcpServerTransport(Transport):
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 11411,
        accept_timeout_s: float = 0.05,
        read_timeout_s: float = 0.05,
    ) -> None:
        self._host = host
        self._port = port
        self._accept_timeout = accept_timeout_s
        self._read_timeout = read_timeout_s
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((host, port))
            srv.listen(1)
            srv.settimeout(accept_timeout_s)
        except OSError as exc:
            raise TransportError(f"bind/listen on {host}:{port} failed: {exc}") from exc
        self._srv: socket.socket | None = srv
        self._client: socket.socket | None = None
        # Track the bound port so callers (and tests) can read it
        # back when port=0 (ephemeral).
        self._bound_port = srv.getsockname()[1]
        self._closed = False

    @property
    def bound_port(self) -> int:
        return self._bound_port

    @property
    def name(self) -> str:
        peer = ""
        if self._client is not None:
            with contextlib.suppress(OSError):
                peer = f" peer={self._client.getpeername()}"
        return f"tcp:{self._host}:{self._bound_port}{peer}"

    def close(self) -> None:
        self._closed = True
        self._drop_client()
        if self._srv is not None:
            with contextlib.suppress(OSError):
                self._srv.close()
            self._srv = None

    def read(self, max_bytes: int) -> bytes:
        if self._closed:
            raise TransportError("tcp transport closed")
        if self._client is None:
            self._try_accept()
            if self._client is None:
                return b""
        r, _, _ = select.select([self._client], [], [], self._read_timeout)
        if not r:
            return b""
        try:
            data = self._client.recv(max_bytes)
        except OSError as exc:
            self._drop_client()
            raise TransportError(f"recv: {exc}") from exc
        if not data:
            self._drop_client()
            raise TransportError("peer closed")
        return data

    def write(self, data: bytes) -> None:
        if self._closed:
            raise TransportError("tcp transport closed")
        if self._client is None:
            # No connection: writes are dropped silently (the device
            # hasn't joined yet). The bridge loop continues.
            return
        try:
            self._client.sendall(data)
        except OSError as exc:
            self._drop_client()
            raise TransportError(f"sendall: {exc}") from exc

    # --- internals ---------------------------------------------------

    def _try_accept(self) -> None:
        if self._srv is None:
            return
        try:
            client, addr = self._srv.accept()
        except TimeoutError:
            return
        except OSError as exc:
            raise TransportError(f"accept: {exc}") from exc
        client.setblocking(False)
        # Disable Nagle: we already send framed chunks, latency matters
        # more than coalescing in this context.
        with contextlib.suppress(OSError):
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._client = client
        logger.info("tcp client connected from %s", addr)

    def _drop_client(self) -> None:
        if self._client is None:
            return
        with contextlib.suppress(OSError):
            self._client.close()
        self._client = None
