"""rosserial2 — host-side bridge for the ESP32 ↔ ROS2 wire protocol."""

from rosserial2 import codec, control
from rosserial2.codec import (
    CRC_SIZE,
    HEADER_SIZE,
    MAX_PAYLOAD,
    OVERHEAD,
    SYNC,
    Frame,
    FrameError,
    FrameParser,
    encode_frame,
)

__all__ = [
    "CRC_SIZE",
    "HEADER_SIZE",
    "MAX_PAYLOAD",
    "OVERHEAD",
    "SYNC",
    "Frame",
    "FrameError",
    "FrameParser",
    "codec",
    "control",
    "encode_frame",
]

__version__ = "0.1.0"
