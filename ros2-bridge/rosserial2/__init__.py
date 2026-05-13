"""rosserial2 — host-side bridge for the ESP32 ↔ ROS2 wire protocol."""

from rosserial2 import codec, control, converters
from rosserial2.bridge import BridgeLoop, PublisherFactory
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
from rosserial2.session import Session, SessionState, TopicEntry

__all__ = [
    "CRC_SIZE",
    "HEADER_SIZE",
    "MAX_PAYLOAD",
    "OVERHEAD",
    "SYNC",
    "BridgeLoop",
    "Frame",
    "FrameError",
    "FrameParser",
    "PublisherFactory",
    "Session",
    "SessionState",
    "TopicEntry",
    "codec",
    "control",
    "converters",
    "encode_frame",
]

__version__ = "0.1.0"
