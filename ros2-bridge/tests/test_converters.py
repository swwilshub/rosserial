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
