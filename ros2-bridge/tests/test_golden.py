"""Golden-frame snapshot tests.

The bytes in ``tests/golden/*.bin`` are the wire format. If they
change, that is a wire-version bump and the change must be
intentional. To regenerate:

    python ros2-bridge/tests/golden/regenerate.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rosserial2.codec import CONTROL_MSG_ID, decode_frame
from rosserial2.control import (
    DEVICE_ID_LEN,
    FW_HASH_LEN,
    Advertise,
    Direction,
    Hello,
    Ping,
    decode_control,
    encode_control,
)

GOLDEN = Path(__file__).resolve().parent / "golden"


def _read(name: str) -> bytes:
    return (GOLDEN / name).read_bytes()


def test_empty_payload_golden() -> None:
    f = decode_frame(_read("empty_payload.bin"))
    assert f.seq == 0 and f.msg_id == 1 and f.payload == b""


def test_ascii_payload_golden() -> None:
    f = decode_frame(_read("ascii_payload.bin"))
    assert f.seq == 42 and f.msg_id == 7 and f.payload == b"hello, rosserial2"


def test_max_payload_golden() -> None:
    f = decode_frame(_read("max_payload.bin"))
    assert f.seq == 255 and f.msg_id == 255
    assert f.payload == bytes(range(256)) * 2


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "hello.bin",
            Hello(
                proto_ver=1,
                device_id=b"\xaa" * DEVICE_ID_LEN,
                fw_hash=b"\xbb" * FW_HASH_LEN,
                max_payload=512,
            ),
        ),
        (
            "advertise.bin",
            Advertise(
                topic_id=7,
                direction=Direction.PUBLISH,
                type_str="std_msgs/msg/String",
                name="chatter",
            ),
        ),
        ("ping.bin", Ping(nonce=0xDEADBEEF)),
    ],
)
def test_control_goldens(name: str, expected: object) -> None:
    f = decode_frame(_read(name))
    assert f.msg_id == CONTROL_MSG_ID
    assert decode_control(f.payload) == expected


def test_golden_bytes_match_re_encode() -> None:
    """Regenerating must produce byte-identical output (bit-for-bit)."""
    from rosserial2.codec import encode_frame

    cases = {
        "empty_payload.bin": (0, 1, b""),
        "ascii_payload.bin": (42, 7, b"hello, rosserial2"),
        "max_payload.bin": (255, 255, bytes(range(256)) * 2),
    }
    for name, (seq, msg_id, payload) in cases.items():
        assert encode_frame(seq, msg_id, payload) == _read(name), name

    control_cases = {
        "hello.bin": (
            0,
            Hello(
                proto_ver=1,
                device_id=b"\xaa" * DEVICE_ID_LEN,
                fw_hash=b"\xbb" * FW_HASH_LEN,
                max_payload=512,
            ),
        ),
        "advertise.bin": (
            1,
            Advertise(
                topic_id=7,
                direction=Direction.PUBLISH,
                type_str="std_msgs/msg/String",
                name="chatter",
            ),
        ),
        "ping.bin": (2, Ping(nonce=0xDEADBEEF)),
    }
    for name, (seq, msg) in control_cases.items():
        assert encode_frame(seq, CONTROL_MSG_ID, encode_control(msg)) == _read(name), name
