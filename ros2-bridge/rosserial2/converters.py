"""Per-type payload converters.

The bridge owns the mapping from a ROS2 type string to a packed byte
layout. See ADR-0006. Each converter has the same shape:

    class Converter(Protocol):
        type_str: str
        def pack(self, value: Any) -> bytes: ...
        def unpack(self, payload: bytes) -> Any: ...

For types that map to actual ROS2 message classes, ``unpack`` returns
either an instance of that class (when rclpy is importable) or a
plain Python value as a stand-in (when not). Tests can use the
stand-in directly without a ROS2 install; the rclpy bridge node
post-processes if needed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Protocol


class ConverterError(ValueError):
    pass


class Converter(Protocol):
    type_str: str

    def pack(self, value: Any) -> bytes: ...
    def unpack(self, payload: bytes) -> Any: ...


@dataclass(frozen=True)
class Int32Converter:
    type_str: str = "std_msgs/msg/Int32"

    def pack(self, value: Any) -> bytes:
        v = int(value)
        if not -(2**31) <= v < 2**31:
            raise ConverterError(f"Int32 out of range: {v}")
        return struct.pack("<i", v)

    def unpack(self, payload: bytes) -> int:
        if len(payload) != 4:
            raise ConverterError(f"Int32 payload must be 4 bytes, got {len(payload)}")
        return struct.unpack("<i", payload)[0]


_REGISTRY: dict[str, Converter] = {
    Int32Converter.type_str: Int32Converter(),
}


def get(type_str: str) -> Converter | None:
    return _REGISTRY.get(type_str)


def register(converter: Converter) -> None:
    _REGISTRY[converter.type_str] = converter


def known_types() -> list[str]:
    return sorted(_REGISTRY)
