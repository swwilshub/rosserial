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


@dataclass(frozen=True)
class StringConverter:
    """Packed layout: ``uint32 length (LE) | UTF-8 bytes``."""

    type_str: str = "std_msgs/msg/String"

    def pack(self, value: Any) -> bytes:
        data = value if isinstance(value, bytes) else str(value).encode("utf-8")
        if len(data) > 0xFFFFFFFF:
            raise ConverterError(f"String too large: {len(data)} bytes")
        return struct.pack("<I", len(data)) + data

    def unpack(self, payload: bytes) -> str:
        if len(payload) < 4:
            raise ConverterError(f"String payload < 4 bytes: {len(payload)}")
        (length,) = struct.unpack("<I", payload[:4])
        if len(payload) != 4 + length:
            raise ConverterError(
                f"String length mismatch: header says {length}, body has {len(payload) - 4}"
            )
        return payload[4:].decode("utf-8")


@dataclass(frozen=True)
class BoolConverter:
    """Packed layout: ``uint8`` (0 or 1)."""

    type_str: str = "std_msgs/msg/Bool"

    def pack(self, value: Any) -> bytes:
        return bytes([1 if bool(value) else 0])

    def unpack(self, payload: bytes) -> bool:
        if len(payload) != 1:
            raise ConverterError(f"Bool payload must be 1 byte, got {len(payload)}")
        return payload[0] != 0


@dataclass(frozen=True)
class Float32Converter:
    """Packed layout: ``float32 LE`` (IEEE 754)."""

    type_str: str = "std_msgs/msg/Float32"

    def pack(self, value: Any) -> bytes:
        return struct.pack("<f", float(value))

    def unpack(self, payload: bytes) -> float:
        if len(payload) != 4:
            raise ConverterError(f"Float32 payload must be 4 bytes, got {len(payload)}")
        return struct.unpack("<f", payload)[0]


_REGISTRY: dict[str, Converter] = {
    BoolConverter.type_str: BoolConverter(),
    Float32Converter.type_str: Float32Converter(),
    Int32Converter.type_str: Int32Converter(),
    StringConverter.type_str: StringConverter(),
}


def get(type_str: str) -> Converter | None:
    return _REGISTRY.get(type_str)


def register(converter: Converter) -> None:
    _REGISTRY[converter.type_str] = converter


def known_types() -> list[str]:
    return sorted(_REGISTRY)
