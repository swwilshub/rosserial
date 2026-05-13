"""Wire-frame codec for rosserial2 protocol v1.

Frame layout (little-endian throughout):

    0xAA 0x55  LEN_LO LEN_HI  SEQ  MSG_ID  PAYLOAD...  CRC32

CRC32 is IEEE 802.3, computed over LEN_LO..end-of-payload. The codec is
pure: no I/O, no globals, no allocation beyond the bytes objects it
returns. A streaming parser is provided for byte-at-a-time use.
"""

from __future__ import annotations

import zlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

SYNC: bytes = b"\xaa\x55"
HEADER_SIZE: int = 6  # SYNC(2) + LEN(2) + SEQ(1) + MSG_ID(1)
CRC_SIZE: int = 4
OVERHEAD: int = HEADER_SIZE + CRC_SIZE  # 10
MAX_PAYLOAD: int = 512
CONTROL_MSG_ID: int = 0


class FrameError(ValueError):
    """Raised when a frame fails validation during decode."""


@dataclass(frozen=True)
class Frame:
    """A decoded frame. ``msg_id == 0`` means control plane."""

    seq: int
    msg_id: int
    payload: bytes

    def __post_init__(self) -> None:
        if not 0 <= self.seq <= 0xFF:
            raise FrameError(f"seq out of range: {self.seq}")
        if not 0 <= self.msg_id <= 0xFF:
            raise FrameError(f"msg_id out of range: {self.msg_id}")
        if len(self.payload) > MAX_PAYLOAD:
            raise FrameError(f"payload too large: {len(self.payload)} > {MAX_PAYLOAD}")


def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def encode_frame(seq: int, msg_id: int, payload: bytes) -> bytes:
    """Encode a single frame to bytes. Validates inputs."""
    if not 0 <= seq <= 0xFF:
        raise FrameError(f"seq out of range: {seq}")
    if not 0 <= msg_id <= 0xFF:
        raise FrameError(f"msg_id out of range: {msg_id}")
    if len(payload) > MAX_PAYLOAD:
        raise FrameError(f"payload too large: {len(payload)} > {MAX_PAYLOAD}")

    length = len(payload)
    crc_region = bytes([length & 0xFF, (length >> 8) & 0xFF, seq, msg_id]) + payload
    crc = _crc32(crc_region)
    return SYNC + crc_region + crc.to_bytes(4, "little")


def decode_frame(buf: bytes) -> Frame:
    """Decode a single complete frame from ``buf``.

    The buffer must contain exactly one frame and nothing else. For
    streaming data, use :class:`FrameParser`.
    """
    if len(buf) < OVERHEAD:
        raise FrameError(f"buffer too short: {len(buf)} < {OVERHEAD}")
    if buf[0:2] != SYNC:
        raise FrameError("bad sync")
    length = buf[2] | (buf[3] << 8)
    if length > MAX_PAYLOAD:
        raise FrameError(f"length out of range: {length}")
    expected_total = OVERHEAD + length
    if len(buf) != expected_total:
        raise FrameError(f"size mismatch: got {len(buf)}, expected {expected_total}")
    seq = buf[4]
    msg_id = buf[5]
    payload = buf[HEADER_SIZE : HEADER_SIZE + length]
    crc_offset = HEADER_SIZE + length
    crc_actual = int.from_bytes(buf[crc_offset : crc_offset + 4], "little")
    crc_expected = _crc32(buf[2:crc_offset])
    if crc_actual != crc_expected:
        raise FrameError(f"crc mismatch: got {crc_actual:#010x}, expected {crc_expected:#010x}")
    return Frame(seq=seq, msg_id=msg_id, payload=bytes(payload))


class FrameParser:
    """Streaming parser. Feed bytes; collect complete frames.

    The parser implements the resync rule from ADR-0002: on any failure
    (bad length, CRC mismatch) it returns to scanning, and resumes from
    the byte *after* the first sync byte of the failed candidate. A
    payload that happens to contain ``0xAA 0x55`` cannot deadlock the
    parser because each candidate either fails the LEN bound or the
    CRC, and the scanner walks past it.

    Implementation: we keep a byte buffer of all unconsumed input. On
    each ``feed()`` we run the scanner until we either produce a frame
    or run out of bytes to make progress. On failure we discard the
    leading 0xAA and continue.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        # Telemetry.
        self.errors: int = 0
        self.bytes_seen: int = 0

    def reset(self) -> None:
        self._buf.clear()

    def feed(self, data: bytes | bytearray | memoryview) -> list[Frame]:
        """Feed bytes; return any complete frames produced."""
        return list(self.feed_iter(data))

    def feed_iter(self, data: bytes | bytearray | memoryview) -> Iterator[Frame]:
        self.bytes_seen += len(data)
        self._buf.extend(data)
        while True:
            frame, advance = self._try_one()
            if advance == 0:
                return
            del self._buf[:advance]
            if frame is not None:
                yield frame

    def _try_one(self) -> tuple[Frame | None, int]:
        """Try to extract one frame from the head of ``_buf``.

        Returns ``(frame, advance)``:
        - ``advance == 0`` means we need more data; nothing was consumed.
        - ``advance > 0`` means consume that many bytes from the head;
          ``frame`` is the produced frame or ``None`` if those bytes
          were garbage (no sync found, or a failed candidate's leading
          ``0xAA``).
        """
        buf = self._buf
        n = len(buf)
        if n == 0:
            return None, 0

        # Scan for sync.
        try:
            start = buf.index(0xAA)
        except ValueError:
            # No 0xAA at all: drop everything (none of it can begin a
            # frame). Need at least one byte to have entered here.
            return None, n

        if start > 0:
            return None, start

        # buf[0] == 0xAA. Need at least 2 bytes to test the second sync.
        if n < 2:
            return None, 0
        if buf[1] != 0x55:
            # Failed sync: drop just the 0xAA and let the scanner retry.
            return None, 1

        # Need full header to read length.
        if n < HEADER_SIZE:
            return None, 0
        length = buf[2] | (buf[3] << 8)
        if length > MAX_PAYLOAD:
            self.errors += 1
            return None, 1  # rewind past the 0xAA
        total = OVERHEAD + length
        if n < total:
            return None, 0

        seq = buf[4]
        msg_id = buf[5]
        payload = bytes(buf[HEADER_SIZE : HEADER_SIZE + length])
        crc_offset = HEADER_SIZE + length
        crc_actual = int.from_bytes(buf[crc_offset : crc_offset + 4], "little")
        crc_expected = _crc32(bytes(buf[2:crc_offset]))
        if crc_actual != crc_expected:
            self.errors += 1
            return None, 1  # rewind past the 0xAA

        frame = Frame(seq=seq, msg_id=msg_id, payload=payload)
        return frame, total


def chunks(data: Iterable[int], size: int) -> Iterator[bytes]:
    """Utility: split ``data`` into ``size``-byte chunks. Used in tests."""
    buf: list[int] = []
    for b in data:
        buf.append(b)
        if len(buf) == size:
            yield bytes(buf)
            buf.clear()
    if buf:
        yield bytes(buf)
