"""Regenerate golden-frame snapshots.

Run from the repo root:

    python ros2-bridge/tests/golden/regenerate.py

This is intentionally NOT wired into pytest. Golden frames change only
when the wire format changes; that is a wire-version bump and an ADR.
"""

from __future__ import annotations

from pathlib import Path

from rosserial2.codec import CONTROL_MSG_ID, encode_frame
from rosserial2.control import (
    DEVICE_ID_LEN,
    FW_HASH_LEN,
    Advertise,
    Direction,
    Hello,
    Ping,
)

HERE = Path(__file__).resolve().parent


def write(name: str, data: bytes) -> None:
    (HERE / name).write_bytes(data)
    print(f"wrote {name}: {len(data)} bytes")


def main() -> None:
    write("empty_payload.bin", encode_frame(seq=0, msg_id=1, payload=b""))
    write(
        "ascii_payload.bin",
        encode_frame(seq=42, msg_id=7, payload=b"hello, rosserial2"),
    )
    write(
        "max_payload.bin",
        encode_frame(seq=255, msg_id=255, payload=bytes(range(256)) * 2),
    )
    write(
        "hello.bin",
        encode_frame(
            seq=0,
            msg_id=CONTROL_MSG_ID,
            payload=Hello(
                proto_ver=1,
                device_id=b"\xaa" * DEVICE_ID_LEN,
                fw_hash=b"\xbb" * FW_HASH_LEN,
                max_payload=512,
            ).encode(),
        ),
    )
    write(
        "advertise.bin",
        encode_frame(
            seq=1,
            msg_id=CONTROL_MSG_ID,
            payload=Advertise(
                topic_id=7,
                direction=Direction.PUBLISH,
                type_str="std_msgs/msg/String",
                name="chatter",
            ).encode(),
        ),
    )
    write(
        "ping.bin",
        encode_frame(
            seq=2,
            msg_id=CONTROL_MSG_ID,
            payload=Ping(nonce=0xDEADBEEF).encode(),
        ),
    )


if __name__ == "__main__":
    main()
