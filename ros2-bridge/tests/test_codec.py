"""Property tests for the wire codec."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rosserial2.codec import (
    CRC_SIZE,
    HEADER_SIZE,
    MAX_PAYLOAD,
    OVERHEAD,
    SYNC,
    Frame,
    FrameError,
    FrameParser,
    decode_frame,
    encode_frame,
)

frame_st = st.builds(
    lambda seq, msg_id, payload: (seq, msg_id, payload),
    seq=st.integers(min_value=0, max_value=0xFF),
    msg_id=st.integers(min_value=0, max_value=0xFF),
    payload=st.binary(min_size=0, max_size=MAX_PAYLOAD),
)


@given(frame_st)
def test_roundtrip_one_shot(args: tuple[int, int, bytes]) -> None:
    seq, msg_id, payload = args
    encoded = encode_frame(seq, msg_id, payload)
    decoded = decode_frame(encoded)
    assert decoded == Frame(seq=seq, msg_id=msg_id, payload=payload)


@given(frame_st)
def test_roundtrip_streaming(args: tuple[int, int, bytes]) -> None:
    seq, msg_id, payload = args
    encoded = encode_frame(seq, msg_id, payload)
    parser = FrameParser()
    out = parser.feed(encoded)
    assert out == [Frame(seq=seq, msg_id=msg_id, payload=payload)]
    assert parser.errors == 0


@given(st.lists(frame_st, min_size=1, max_size=20))
def test_streaming_multiple_frames(args_list: list[tuple[int, int, bytes]]) -> None:
    expected = [Frame(seq=s, msg_id=m, payload=p) for s, m, p in args_list]
    encoded = b"".join(encode_frame(s, m, p) for s, m, p in args_list)
    parser = FrameParser()
    got = parser.feed(encoded)
    assert got == expected
    assert parser.errors == 0


@given(
    st.lists(frame_st, min_size=1, max_size=10),
    st.integers(min_value=1, max_value=64),
)
def test_streaming_arbitrary_chunking(
    args_list: list[tuple[int, int, bytes]], chunk: int
) -> None:
    """Frames must decode regardless of how the byte stream is split."""
    expected = [Frame(seq=s, msg_id=m, payload=p) for s, m, p in args_list]
    encoded = b"".join(encode_frame(s, m, p) for s, m, p in args_list)
    parser = FrameParser()
    got: list[Frame] = []
    for i in range(0, len(encoded), chunk):
        got.extend(parser.feed(encoded[i : i + chunk]))
    assert got == expected
    assert parser.errors == 0


def test_overhead_constant() -> None:
    """OVERHEAD must equal HEADER_SIZE + CRC_SIZE; locks the spec."""
    assert OVERHEAD == HEADER_SIZE + CRC_SIZE
    assert HEADER_SIZE == 6
    assert CRC_SIZE == 4
    assert OVERHEAD == 10
    assert SYNC == b"\xaa\x55"


def test_encode_rejects_oversize_payload() -> None:
    with pytest.raises(FrameError):
        encode_frame(0, 1, b"\x00" * (MAX_PAYLOAD + 1))


def test_encode_rejects_bad_seq() -> None:
    with pytest.raises(FrameError):
        encode_frame(-1, 1, b"")
    with pytest.raises(FrameError):
        encode_frame(256, 1, b"")


def test_encode_rejects_bad_msg_id() -> None:
    with pytest.raises(FrameError):
        encode_frame(0, -1, b"")
    with pytest.raises(FrameError):
        encode_frame(0, 256, b"")


def test_decode_rejects_short() -> None:
    with pytest.raises(FrameError):
        decode_frame(b"\xaa\x55")


def test_decode_rejects_bad_sync() -> None:
    encoded = bytearray(encode_frame(0, 1, b"hi"))
    encoded[0] = 0x00
    with pytest.raises(FrameError):
        decode_frame(bytes(encoded))


def test_decode_rejects_bad_crc() -> None:
    encoded = bytearray(encode_frame(7, 9, b"abc"))
    encoded[-1] ^= 0x01
    with pytest.raises(FrameError):
        decode_frame(bytes(encoded))


def test_decode_rejects_oversize_length() -> None:
    # Hand-craft a header claiming length > MAX_PAYLOAD.
    bad_len = (MAX_PAYLOAD + 1).to_bytes(2, "little")
    crafted = SYNC + bad_len + b"\x00\x00" + b"\x00" * (MAX_PAYLOAD + 1) + b"\x00\x00\x00\x00"
    with pytest.raises(FrameError):
        decode_frame(crafted)


@given(
    frame_st,
    st.integers(min_value=0, max_value=10000),  # bit position
)
@settings(max_examples=200)
def test_single_bit_flip_detected(args: tuple[int, int, bytes], pos: int) -> None:
    """Any single-bit flip in a frame must either fail decode or yield
    a different frame than the original.
    """
    seq, msg_id, payload = args
    encoded = bytearray(encode_frame(seq, msg_id, payload))
    bit = pos % (len(encoded) * 8)
    byte_idx, bit_idx = divmod(bit, 8)
    encoded[byte_idx] ^= 1 << bit_idx
    try:
        got = decode_frame(bytes(encoded))
    except FrameError:
        return  # detected
    assert got != Frame(seq=seq, msg_id=msg_id, payload=payload)


def test_zero_payload_roundtrip() -> None:
    encoded = encode_frame(0, 1, b"")
    assert len(encoded) == OVERHEAD
    assert decode_frame(encoded) == Frame(seq=0, msg_id=1, payload=b"")


def test_max_payload_roundtrip() -> None:
    payload = bytes(range(256)) * 2  # 512 bytes
    assert len(payload) == MAX_PAYLOAD
    encoded = encode_frame(255, 255, payload)
    assert decode_frame(encoded) == Frame(seq=255, msg_id=255, payload=payload)


def test_seq_wrap() -> None:
    """seq is u8; wrapping is the caller's responsibility but must encode."""
    encoded = encode_frame(0xFF, 0, b"x")
    assert decode_frame(encoded).seq == 0xFF
