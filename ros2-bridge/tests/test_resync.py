"""Resync-bound tests.

ADR-0002 commits to a documented resync bound: after arbitrary
corruption ends, the parser must lock onto the next valid frame within
``MAX_PAYLOAD + 10`` bytes. These tests are the regression gate.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from rosserial2.codec import (
    MAX_PAYLOAD,
    OVERHEAD,
    Frame,
    FrameParser,
    encode_frame,
)

frame_st = st.builds(
    lambda seq, msg_id, payload: (seq, msg_id, payload),
    seq=st.integers(min_value=0, max_value=0xFF),
    msg_id=st.integers(min_value=0, max_value=0xFF),
    payload=st.binary(min_size=0, max_size=MAX_PAYLOAD),
)


@given(
    junk=st.binary(min_size=0, max_size=2048),
    args=frame_st,
)
def test_arbitrary_prefix_then_valid(junk: bytes, args: tuple[int, int, bytes]) -> None:
    """A valid frame after arbitrary junk must still decode."""
    seq, msg_id, payload = args
    encoded = encode_frame(seq, msg_id, payload)
    parser = FrameParser()
    out = parser.feed(junk + encoded)
    assert Frame(seq=seq, msg_id=msg_id, payload=payload) in out


@given(
    pre=st.binary(min_size=0, max_size=512),
    args1=frame_st,
    middle_junk=st.binary(min_size=0, max_size=512),
    args2=frame_st,
)
@settings(max_examples=300)
def test_two_frames_with_junk_between(
    pre: bytes,
    args1: tuple[int, int, bytes],
    middle_junk: bytes,
    args2: tuple[int, int, bytes],
) -> None:
    s1, m1, p1 = args1
    s2, m2, p2 = args2
    enc1 = encode_frame(s1, m1, p1)
    enc2 = encode_frame(s2, m2, p2)
    parser = FrameParser()
    out = parser.feed(pre + enc1 + middle_junk + enc2)
    assert Frame(seq=s1, msg_id=m1, payload=p1) in out
    assert Frame(seq=s2, msg_id=m2, payload=p2) in out


@given(args=frame_st, drop_at=st.integers(min_value=0))
@settings(max_examples=200)
def test_truncated_frame_does_not_break_following(
    args: tuple[int, int, bytes],
    drop_at: int,
) -> None:
    """A truncated frame must not poison the parser for the next one.

    The parser is streaming: a truncated frame whose claimed length is
    inflated may legitimately wait for more bytes. We feed enough
    trailing data (payload-of-zeros pad) for the rewind path to
    rediscover the next sync within the documented MAX_PAYLOAD + OVERHEAD
    resync bound.
    """
    seq, msg_id, payload = args
    enc = encode_frame(seq, msg_id, payload)
    cut = drop_at % len(enc)
    truncated = enc[:cut]
    follow = encode_frame(0, 0, b"after")
    pad = b"\x00" * (MAX_PAYLOAD + OVERHEAD)
    parser = FrameParser()
    out = parser.feed(truncated + follow + pad)
    assert Frame(seq=0, msg_id=0, payload=b"after") in out


@given(
    args=frame_st,
    flip_at=st.integers(min_value=0, max_value=10000),
)
@settings(max_examples=200)
def test_corrupted_frame_recovers_on_next(
    args: tuple[int, int, bytes],
    flip_at: int,
) -> None:
    """Bit-flip in frame N → parser still locks onto frame N+1.

    A flip in the LEN field can inflate the claimed payload length, so
    the parser legitimately waits for those bytes. We pad with enough
    trailing bytes for the rewind path to rediscover sync within the
    documented MAX_PAYLOAD + OVERHEAD resync bound.
    """
    seq, msg_id, payload = args
    bad = bytearray(encode_frame(seq, msg_id, payload))
    bit = flip_at % (len(bad) * 8)
    byte_idx, bit_idx = divmod(bit, 8)
    bad[byte_idx] ^= 1 << bit_idx
    follow = encode_frame((seq + 1) & 0xFF, msg_id, b"recovered")
    pad = b"\x00" * (MAX_PAYLOAD + OVERHEAD)
    parser = FrameParser()
    out = parser.feed(bytes(bad) + follow + pad)
    assert Frame(seq=(seq + 1) & 0xFF, msg_id=msg_id, payload=b"recovered") in out


def test_resync_bound_explicit() -> None:
    """After corruption ends, lock within MAX_PAYLOAD + OVERHEAD bytes."""
    # Worst-case junk: MAX_PAYLOAD bytes of 0xAA which look like sync starts.
    junk = b"\xaa" * (MAX_PAYLOAD + OVERHEAD)
    valid = encode_frame(42, 7, b"hello")
    parser = FrameParser()
    out = parser.feed(junk + valid)
    assert Frame(seq=42, msg_id=7, payload=b"hello") in out


def test_payload_containing_sync_bytes() -> None:
    """A payload that legally contains 0xAA 0x55 must not confuse the parser."""
    nasty = b"\xaa\x55" * 100
    enc = encode_frame(1, 1, nasty)
    follow = encode_frame(2, 2, b"next")
    parser = FrameParser()
    out = parser.feed(enc + follow)
    assert Frame(seq=1, msg_id=1, payload=nasty) in out
    assert Frame(seq=2, msg_id=2, payload=b"next") in out


def test_payload_looks_like_inner_frame() -> None:
    """Payload that begins with a plausible-looking inner frame header."""
    inner = encode_frame(99, 99, b"trickster")  # full valid inner frame
    enc = encode_frame(1, 1, inner)  # wrapped as payload
    follow = encode_frame(2, 2, b"after")
    parser = FrameParser()
    out = parser.feed(enc + follow)
    # The outer frame must come out intact, and the next real frame too.
    assert Frame(seq=1, msg_id=1, payload=inner) in out
    assert Frame(seq=2, msg_id=2, payload=b"after") in out
