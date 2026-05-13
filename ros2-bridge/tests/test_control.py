"""Property tests for the control-plane codec."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rosserial2.control import (
    DEVICE_ID_LEN,
    FW_HASH_LEN,
    Advertise,
    AdvertiseAck,
    Bye,
    ControlError,
    Direction,
    Hello,
    HelloAck,
    Log,
    Opcode,
    Ping,
    Pong,
    decode_control,
    encode_control,
)

# Constrain string strategies to lengths that fit in one byte and to
# UTF-8 that doesn't blow the 255-byte limit when encoded.
short_text = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
    min_size=1,
    max_size=64,
)


@given(
    proto_ver=st.integers(min_value=0, max_value=0xFF),
    device_id=st.binary(min_size=DEVICE_ID_LEN, max_size=DEVICE_ID_LEN),
    fw_hash=st.binary(min_size=FW_HASH_LEN, max_size=FW_HASH_LEN),
    max_payload=st.integers(min_value=0, max_value=0xFFFF),
)
def test_hello_roundtrip(
    proto_ver: int, device_id: bytes, fw_hash: bytes, max_payload: int
) -> None:
    msg = Hello(
        proto_ver=proto_ver,
        device_id=device_id,
        fw_hash=fw_hash,
        max_payload=max_payload,
    )
    got = decode_control(encode_control(msg))
    assert got == msg


@given(
    proto_ver=st.integers(min_value=0, max_value=0xFF),
    accepted=st.integers(min_value=0, max_value=0xFF),
    session_id=st.integers(min_value=0, max_value=0xFFFFFFFF),
)
def test_hello_ack_roundtrip(proto_ver: int, accepted: int, session_id: int) -> None:
    msg = HelloAck(proto_ver=proto_ver, accepted=accepted, session_id=session_id)
    got = decode_control(encode_control(msg))
    assert got == msg


@given(
    topic_id=st.integers(min_value=1, max_value=0xFF),
    direction=st.sampled_from([Direction.PUBLISH, Direction.SUBSCRIBE]),
    type_str=short_text,
    name=short_text,
)
def test_advertise_roundtrip(
    topic_id: int, direction: Direction, type_str: str, name: str
) -> None:
    msg = Advertise(topic_id=topic_id, direction=direction, type_str=type_str, name=name)
    got = decode_control(encode_control(msg))
    assert got == msg


@given(
    topic_id=st.integers(min_value=1, max_value=0xFF),
    accepted=st.integers(min_value=0, max_value=0xFF),
)
def test_advertise_ack_roundtrip(topic_id: int, accepted: int) -> None:
    msg = AdvertiseAck(topic_id=topic_id, accepted=accepted)
    got = decode_control(encode_control(msg))
    assert got == msg


@given(nonce=st.integers(min_value=0, max_value=0xFFFFFFFF))
def test_ping_pong_roundtrip(nonce: int) -> None:
    assert decode_control(encode_control(Ping(nonce=nonce))) == Ping(nonce=nonce)
    assert decode_control(encode_control(Pong(nonce=nonce))) == Pong(nonce=nonce)


@given(
    level=st.integers(min_value=0, max_value=0xFF),
    message=st.text(max_size=200),
)
def test_log_roundtrip(level: int, message: str) -> None:
    msg = Log(level=level, message=message)
    got = decode_control(encode_control(msg))
    assert got == msg


@given(reason=st.integers(min_value=0, max_value=0xFF))
def test_bye_roundtrip(reason: int) -> None:
    msg = Bye(reason=reason)
    got = decode_control(encode_control(msg))
    assert got == msg


def test_unknown_opcode() -> None:
    with pytest.raises(ControlError):
        decode_control(b"\x00")


def test_empty_payload() -> None:
    with pytest.raises(ControlError):
        decode_control(b"")


def test_truncated_hello() -> None:
    with pytest.raises(ControlError):
        decode_control(bytes([Opcode.HELLO]) + b"\x01" * 5)


def test_truncated_advertise() -> None:
    with pytest.raises(ControlError):
        decode_control(bytes([Opcode.ADVERTISE, 1, 0, 10]) + b"abc")


def test_advertise_rejects_bad_direction() -> None:
    bad = bytes([Opcode.ADVERTISE, 1, 2, 1, ord("a"), 1, ord("b")])
    with pytest.raises(ControlError):
        decode_control(bad)


def test_advertise_rejects_empty_name() -> None:
    with pytest.raises(ControlError):
        Advertise(topic_id=1, direction=Direction.PUBLISH, type_str="x", name="")


def test_advertise_rejects_topic_id_zero() -> None:
    with pytest.raises(ControlError):
        Advertise(topic_id=0, direction=Direction.PUBLISH, type_str="x", name="y")


def test_hello_rejects_bad_id_len() -> None:
    with pytest.raises(ControlError):
        Hello(proto_ver=1, device_id=b"\x00" * 4, fw_hash=b"\x00" * FW_HASH_LEN, max_payload=512)
