"""End-to-end integration test via a pseudoterminal.

The bridge talks to one end of a pty; the test drives the other end
as a fake firmware device. No ROS2 is required — the publisher
factory hands back a recorder that captures published values.

If a real bring-up fails, this test is the first thing to run.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field

import pytest

from rosserial2 import converters
from rosserial2.bridge import BridgeLoop
from rosserial2.codec import CONTROL_MSG_ID, FrameParser, encode_frame
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
from rosserial2.transports.pty import PtyTransport

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="pty integration test requires POSIX",
)


@dataclass
class _Recorder:
    type_str: str
    name: str
    published: list[object] = field(default_factory=list)

    def publish(self, value: object) -> None:
        self.published.append(value)


@dataclass
class _Factory:
    created: list[_Recorder] = field(default_factory=list)

    def __call__(self, type_str: str, name: str):
        rec = _Recorder(type_str=type_str, name=name)
        self.created.append(rec)
        return rec


def _drive(loop: BridgeLoop, deadline_s: float = 1.0) -> None:
    """Run the bridge until it makes no more progress, bounded."""
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if not loop.run_once():
            return


def _read_until_frame(parser: FrameParser, fd: int, deadline_s: float = 1.0):
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            data = os.read(fd, 4096)
        except BlockingIOError:
            data = b""
        if data:
            frames = parser.feed(data)
            if frames:
                return frames
        time.sleep(0.005)
    raise AssertionError("timed out waiting for a frame from the bridge")


def _send(fd: int, raw: bytes) -> None:
    os.write(fd, raw)


def test_hello_handshake_over_pty() -> None:
    factory = _Factory()
    bridge_t, device_fd = PtyTransport.open_pair()
    loop = BridgeLoop(transport=bridge_t, publisher_factory=factory)

    device_parser = FrameParser()
    hello = Hello(
        proto_ver=1,
        device_id=b"\x11" * DEVICE_ID_LEN,
        fw_hash=b"\x22" * FW_HASH_LEN,
        max_payload=512,
    )
    _send(device_fd, encode_frame(seq=0, msg_id=CONTROL_MSG_ID, payload=hello.encode()))

    try:
        _drive(loop)
        frames = _read_until_frame(device_parser, device_fd)
        assert len(frames) == 1
        reply = decode_control(frames[0].payload)
        assert isinstance(reply, HelloAck)
        assert reply.accepted == 1
        assert reply.session_id == 1
    finally:
        os.close(device_fd)
        bridge_t.close()


def test_full_advertise_and_publish_cycle() -> None:
    factory = _Factory()
    bridge_t, device_fd = PtyTransport.open_pair()
    loop = BridgeLoop(transport=bridge_t, publisher_factory=factory)
    device_parser = FrameParser()

    try:
        # 1) HELLO + HELLO_ACK
        hello = Hello(
            proto_ver=1,
            device_id=b"\x33" * DEVICE_ID_LEN,
            fw_hash=b"\x44" * FW_HASH_LEN,
            max_payload=512,
        )
        _send(device_fd, encode_frame(0, CONTROL_MSG_ID, hello.encode()))
        _drive(loop)
        [hf] = _read_until_frame(device_parser, device_fd)
        assert isinstance(decode_control(hf.payload), HelloAck)

        # 2) ADVERTISE int32 → ADVERTISE_ACK accepted=1; publisher created.
        adv = Advertise(
            topic_id=7,
            direction=Direction.PUBLISH,
            type_str="std_msgs/msg/Int32",
            name="counter",
        )
        _send(device_fd, encode_frame(1, CONTROL_MSG_ID, adv.encode()))
        _drive(loop)
        [af] = _read_until_frame(device_parser, device_fd)
        ack = decode_control(af.payload)
        assert isinstance(ack, AdvertiseAck) and ack.accepted == 1
        assert len(factory.created) == 1
        recorder = factory.created[0]
        assert recorder.type_str == "std_msgs/msg/Int32"
        assert recorder.name == "counter"

        # 3) Device publishes three counter values.
        conv = converters.get("std_msgs/msg/Int32")
        assert conv is not None
        for i, value in enumerate([1, 42, -7], start=2):
            _send(device_fd, encode_frame(i, 7, conv.pack(value)))
        _drive(loop)
        assert recorder.published == [1, 42, -7]

        # 4) PING from device → PONG from bridge with the same nonce.
        _send(device_fd, encode_frame(5, CONTROL_MSG_ID, Ping(nonce=0xCAFEBABE).encode()))
        _drive(loop)
        [pf] = _read_until_frame(device_parser, device_fd)
        pong = decode_control(pf.payload)
        assert isinstance(pong, Pong) and pong.nonce == 0xCAFEBABE
    finally:
        os.close(device_fd)
        bridge_t.close()


def test_advertise_unknown_type_is_rejected() -> None:
    factory = _Factory()
    bridge_t, device_fd = PtyTransport.open_pair()
    loop = BridgeLoop(transport=bridge_t, publisher_factory=factory)
    device_parser = FrameParser()

    try:
        # HELLO
        hello = Hello(
            proto_ver=1,
            device_id=b"\x55" * DEVICE_ID_LEN,
            fw_hash=b"\x66" * FW_HASH_LEN,
            max_payload=512,
        )
        _send(device_fd, encode_frame(0, CONTROL_MSG_ID, hello.encode()))
        _drive(loop)
        _read_until_frame(device_parser, device_fd)

        # ADVERTISE bogus type
        adv = Advertise(
            topic_id=3,
            direction=Direction.PUBLISH,
            type_str="weirdpkg/msg/NotReal",
            name="ghost",
        )
        _send(device_fd, encode_frame(1, CONTROL_MSG_ID, adv.encode()))
        _drive(loop)
        frames = _read_until_frame(device_parser, device_fd)
        # Bridge replies with ADVERTISE_ACK accepted=0 and a LOG frame.
        ops = [decode_control(f.payload) for f in frames]
        ack_frames = [m for m in ops if hasattr(m, "topic_id") and hasattr(m, "accepted")]
        assert ack_frames and ack_frames[0].accepted == 0
        assert factory.created == []
    finally:
        os.close(device_fd)
        bridge_t.close()


def test_reconnect_resets_topic_table() -> None:
    factory = _Factory()
    bridge_t, device_fd = PtyTransport.open_pair()
    loop = BridgeLoop(transport=bridge_t, publisher_factory=factory)
    device_parser = FrameParser()

    try:
        # First session.
        h = Hello(
            proto_ver=1,
            device_id=b"\x77" * DEVICE_ID_LEN,
            fw_hash=b"\x88" * FW_HASH_LEN,
            max_payload=512,
        )
        _send(device_fd, encode_frame(0, CONTROL_MSG_ID, h.encode()))
        _drive(loop)
        _read_until_frame(device_parser, device_fd)
        adv = Advertise(topic_id=1, direction=Direction.PUBLISH,
                        type_str="std_msgs/msg/Int32", name="alpha")
        _send(device_fd, encode_frame(1, CONTROL_MSG_ID, adv.encode()))
        _drive(loop)
        _read_until_frame(device_parser, device_fd)
        assert len(factory.created) == 1

        # Device reconnects: a fresh HELLO must wipe topic table.
        _send(device_fd, encode_frame(2, CONTROL_MSG_ID, h.encode()))
        _drive(loop)
        _read_until_frame(device_parser, device_fd)
        assert loop.session.topics == {}

        # Re-advertise on the new session — a new publisher is created.
        _send(device_fd, encode_frame(3, CONTROL_MSG_ID, adv.encode()))
        _drive(loop)
        _read_until_frame(device_parser, device_fd)
        assert len(factory.created) == 2
    finally:
        os.close(device_fd)
        bridge_t.close()
