"""Tests for the per-type converter registry."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rosserial2 import converters
from rosserial2.converters import ConverterError, Int32Converter


def test_registry_knows_int32() -> None:
    assert "std_msgs/msg/Int32" in converters.known_types()
    conv = converters.get("std_msgs/msg/Int32")
    assert conv is not None


def test_unknown_type_returns_none() -> None:
    assert converters.get("not_a_pkg/msg/Bogus") is None


@given(value=st.integers(min_value=-(2**31), max_value=2**31 - 1))
def test_int32_roundtrip(value: int) -> None:
    conv = Int32Converter()
    assert conv.unpack(conv.pack(value)) == value


def test_int32_out_of_range() -> None:
    conv = Int32Converter()
    with pytest.raises(ConverterError):
        conv.pack(2**31)
    with pytest.raises(ConverterError):
        conv.pack(-(2**31) - 1)


def test_int32_bad_length() -> None:
    conv = Int32Converter()
    with pytest.raises(ConverterError):
        conv.unpack(b"\x00\x00\x00")
    with pytest.raises(ConverterError):
        conv.unpack(b"\x00\x00\x00\x00\x00")


def test_int32_known_bytes() -> None:
    """Wire-level sanity: pack(1) == 01 00 00 00."""
    conv = Int32Converter()
    assert conv.pack(1) == b"\x01\x00\x00\x00"
    assert conv.pack(-1) == b"\xff\xff\xff\xff"
    assert conv.pack(0x12345678) == b"\x78\x56\x34\x12"


def test_registry_knows_string() -> None:
    assert "std_msgs/msg/String" in converters.known_types()


@given(text=st.text(max_size=1024))
def test_string_roundtrip(text: str) -> None:
    from rosserial2.converters import StringConverter

    conv = StringConverter()
    assert conv.unpack(conv.pack(text)) == text


def test_string_known_bytes() -> None:
    from rosserial2.converters import StringConverter

    conv = StringConverter()
    assert conv.pack("hi") == b"\x02\x00\x00\x00hi"
    assert conv.pack("") == b"\x00\x00\x00\x00"


def test_string_rejects_truncated() -> None:
    from rosserial2.converters import StringConverter

    conv = StringConverter()
    with pytest.raises(ConverterError):
        conv.unpack(b"\x05\x00\x00\x00ab")  # claims 5, has 2
    with pytest.raises(ConverterError):
        conv.unpack(b"\x00\x00")  # no header


def test_registry_knows_bool_and_float32() -> None:
    assert "std_msgs/msg/Bool" in converters.known_types()
    assert "std_msgs/msg/Float32" in converters.known_types()


@given(value=st.booleans())
def test_bool_roundtrip(value: bool) -> None:
    from rosserial2.converters import BoolConverter

    conv = BoolConverter()
    assert conv.unpack(conv.pack(value)) is value


def test_bool_wire_bytes() -> None:
    from rosserial2.converters import BoolConverter

    conv = BoolConverter()
    assert conv.pack(True) == b"\x01"
    assert conv.pack(False) == b"\x00"
    # Any non-zero byte unpacks as True (defensive, mirrors Bool semantics).
    assert conv.unpack(b"\x7f") is True


def test_bool_rejects_bad_length() -> None:
    from rosserial2.converters import BoolConverter

    conv = BoolConverter()
    with pytest.raises(ConverterError):
        conv.unpack(b"")
    with pytest.raises(ConverterError):
        conv.unpack(b"\x00\x00")


@given(value=st.floats(allow_nan=False, allow_infinity=False, width=32))
def test_float32_roundtrip(value: float) -> None:
    from rosserial2.converters import Float32Converter

    conv = Float32Converter()
    got = conv.unpack(conv.pack(value))
    # Float32 may quantize at the edges; the pack round-trip should be exact
    # because we already restricted the input to 32-bit-representable floats.
    assert got == value


def test_float32_wire_bytes() -> None:
    from rosserial2.converters import Float32Converter

    conv = Float32Converter()
    # 1.0f in IEEE 754 single = 0x3F800000 (little-endian → 00 00 80 3F)
    assert conv.pack(1.0) == b"\x00\x00\x80\x3f"


def test_float32_rejects_bad_length() -> None:
    from rosserial2.converters import Float32Converter

    conv = Float32Converter()
    with pytest.raises(ConverterError):
        conv.unpack(b"\x00\x00\x00")
    with pytest.raises(ConverterError):
        conv.unpack(b"\x00\x00\x00\x00\x00")
