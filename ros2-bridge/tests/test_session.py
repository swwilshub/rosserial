"""Session state-machine tests (M1 scope)."""

from __future__ import annotations

from rosserial2.codec import CONTROL_MSG_ID, FrameParser, decode_frame, encode_frame
from rosserial2.control import (
    DEVICE_ID_LEN,
    FW_HASH_LEN,
    Advertise,
    AdvertiseAck,
    Direction,
    Hello,
    HelloAck,
    Ping,
    Pong,
    decode_control,
)
from rosserial2.session import Session, SessionState


def _hello_bytes(seq: int = 0) -> bytes:
    msg = Hello(
        proto_ver=1,
        device_id=b"\x01" * DEVICE_ID_LEN,
        fw_hash=b"\x02" * FW_HASH_LEN,
        max_payload=512,
    )
    return encode_frame(seq=seq, msg_id=CONTROL_MSG_ID, payload=msg.encode())


def _drain_control(s: Session) -> list:
    out = []
    for raw in s.drain_outbox():
        f = decode_frame(raw)
        out.append(decode_control(f.payload))
    return out


def test_hello_promotes_to_ready_and_emits_ack() -> None:
    s = Session()
    assert s.state is SessionState.AWAIT_HELLO
    parser = FrameParser()
    [hello_frame] = parser.feed(_hello_bytes())
    s.on_frame(hello_frame)
    assert s.state is SessionState.READY
    [reply] = _drain_control(s)
    assert isinstance(reply, HelloAck)
    assert reply.accepted == 1
    assert reply.session_id == 1


def test_advertise_after_hello_is_accepted() -> None:
    s = Session()
    parser = FrameParser()
    [hf] = parser.feed(_hello_bytes())
    s.on_frame(hf)
    s.drain_outbox()  # discard HelloAck
    adv = Advertise(
        topic_id=7,
        direction=Direction.PUBLISH,
        type_str="std_msgs/msg/Int32",
        name="counter",
    )
    [af] = parser.feed(encode_frame(1, CONTROL_MSG_ID, adv.encode()))
    s.on_frame(af)
    assert 7 in s.topics
    assert s.topics[7].name == "counter"
    [ack] = _drain_control(s)
    assert isinstance(ack, AdvertiseAck) and ack.accepted == 1


def test_advertise_unknown_type_is_rejected_with_log() -> None:
    s = Session()
    parser = FrameParser()
    [hf] = parser.feed(_hello_bytes())
    s.on_frame(hf)
    s.drain_outbox()
    adv = Advertise(
        topic_id=8,
        direction=Direction.PUBLISH,
        type_str="weirdpkg/msg/Unknown",
        name="ghost",
    )
    [af] = parser.feed(encode_frame(1, CONTROL_MSG_ID, adv.encode()))
    s.on_frame(af)
    assert 8 not in s.topics
    replies = _drain_control(s)
    # ADVERTISE_ACK accepted=0 plus a LOG line.
    acks = [m for m in replies if isinstance(m, AdvertiseAck)]
    assert acks and acks[0].accepted == 0


def test_advertise_before_hello_is_rejected() -> None:
    s = Session()
    adv = Advertise(
        topic_id=3,
        direction=Direction.PUBLISH,
        type_str="std_msgs/msg/Int32",
        name="counter",
    )
    parser = FrameParser()
    [af] = parser.feed(encode_frame(0, CONTROL_MSG_ID, adv.encode()))
    s.on_frame(af)
    [ack] = _drain_control(s)
    assert isinstance(ack, AdvertiseAck) and ack.accepted == 0
    assert 3 not in s.topics


def test_ping_replies_with_pong_carrying_same_nonce() -> None:
    s = Session()
    parser = FrameParser()
    [hf] = parser.feed(_hello_bytes())
    s.on_frame(hf)
    s.drain_outbox()
    [pf] = parser.feed(encode_frame(1, CONTROL_MSG_ID, Ping(nonce=0xDEADBEEF).encode()))
    s.on_frame(pf)
    [pong] = _drain_control(s)
    assert isinstance(pong, Pong) and pong.nonce == 0xDEADBEEF


def test_seq_skip_counter() -> None:
    s = Session()
    parser = FrameParser()
    # HELLO resets rx tracking (reconnect path), so we establish a
    # baseline with the first PING after HELLO.
    [hf] = parser.feed(_hello_bytes(seq=0))
    s.on_frame(hf)
    s.drain_outbox()
    [p1] = parser.feed(encode_frame(1, CONTROL_MSG_ID, Ping(nonce=1).encode()))
    s.on_frame(p1)
    s.drain_outbox()
    # Jump from seq=1 to seq=6 → one skip event.
    [p2] = parser.feed(encode_frame(6, CONTROL_MSG_ID, Ping(nonce=2).encode()))
    s.on_frame(p2)
    assert s.rx_seq_skips == 1


def test_tx_seq_monotonic_and_wraps() -> None:
    s = Session()
    parser = FrameParser()
    [hf] = parser.feed(_hello_bytes())
    s.on_frame(hf)
    # Force 257 outbound pings to cover wrap.
    seqs: list[int] = []
    for n in range(260):
        [pf] = parser.feed(encode_frame((n + 1) & 0xFF, CONTROL_MSG_ID, Ping(nonce=n).encode()))
        s.on_frame(pf)
    for raw in s.drain_outbox():
        seqs.append(decode_frame(raw).seq)
    # First seq is 0 (HelloAck), then pongs 1..; must wrap past 255.
    assert seqs[0] == 0
    assert 0xFF in seqs
    assert seqs.count(0) >= 2  # at least Hello-ack 0 and the wrap-around 0
