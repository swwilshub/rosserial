"""pyserial-backed UART transport.

Imported lazily so that running the codec tests does not require a
serial port library to be installed at test time. (pyserial is a
declared dependency, but tests should remain pure.)
"""

from __future__ import annotations

import contextlib

from rosserial2.transport import Transport, TransportError


class SerialTransport(Transport):
    def __init__(self, port: str, baud: int = 921600, timeout: float = 0.05) -> None:
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised on real install
            raise TransportError("pyserial is not installed") from exc
        self._port_name = port
        try:
            self._ser = serial.Serial(port=port, baudrate=baud, timeout=timeout)
        except Exception as exc:  # pyserial raises serial.SerialException
            raise TransportError(f"failed to open {port}: {exc}") from exc

    def read(self, max_bytes: int) -> bytes:
        try:
            return self._ser.read(max_bytes)
        except Exception as exc:
            raise TransportError(str(exc)) from exc

    def write(self, data: bytes) -> None:
        try:
            self._ser.write(data)
        except Exception as exc:
            raise TransportError(str(exc)) from exc

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._ser.close()

    @property
    def name(self) -> str:
        return f"serial:{self._port_name}"
