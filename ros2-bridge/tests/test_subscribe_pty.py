"""End-to-end subscribe path: ROS2 → device via the bridge.

A device advertises a subscribe-direction topic; the test plays the
role of ROS2 by calling the on_message forwarder directly; the bridge
must emit a data frame to the device with the correct topic id.
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
    decode_control,
)
from rosserial2.transports.pty import PtyTransport

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="pty integration test requires POSIX",
)


@dataclass
class _Subscription:
    type_str: str
    name: str
    on_message: object
    destroyed: bool = False

    def destroy(self) -> None:
        self.destroyed = True


@dataclass
class _SubFactory:
    created: list[_Subscription] = field(default_factory=list)

    def __call__(self, type_str: str, name: str, on_message):
        sub = _Subscription(type_str, name, on_message)
        self.created.append(sub)
        return sub


def _drive(loop: BridgeLoop, deadline_s: float = 1.0) -> None:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if not loop.run_once():
            return


def _read_frames(parser: FrameParser, fd: int, deadline_s: float = 1.0):
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
    raise AssertionError("timed out waiting for a frame")


class _FakeMessage:
    """Stand-in for a rclpy message — has a ``data`` attribute."""

    def __init__(self, data: object) -> None:
        self.data = data


def test_subscribe_int32_forwards_to_device() -> None:
    sub_factory = _SubFactory()
    bridge_t, device_fd = PtyTransport.open_pair()
    loop = BridgeLoop(
        transport=bridge_t,
        publisher_factory=lambda *a, **k: None,  # device only subscribes here
        subscription_factory=sub_factory,
    )
    parser = FrameParser()

    try:
        # HELLO
        hello = Hello(
            proto_ver=1,
            device_id=b"\x10" * DEVICE_ID_LEN,
            fw_hash=b"\x20" * FW_HASH_LEN,
            max_payload=512,
        )
        os.write(device_fd, encode_frame(0, CONTROL_MSG_ID, hello.encode()))
        _drive(loop)
        [hf] = _read_frames(parser, device_fd)
        assert isinstance(decode_control(hf.payload), HelloAck)

        # ADVERTISE direction=SUBSCRIBE
        adv = Advertise(
            topic_id=12,
            direction=Direction.SUBSCRIBE,
            type_str="std_msgs/msg/Int32",
            name="cmd",
        )
        os.write(device_fd, encode_frame(1, CONTROL_MSG_ID, adv.encode()))
        _drive(loop)
        [af] = _read_frames(parser, device_fd)
        ack = decode_control(af.payload)
        assert isinstance(ack, AdvertiseAck) and ack.accepted == 1
        assert len(sub_factory.created) == 1
        sub = sub_factory.created[0]
        assert sub.type_str == "std_msgs/msg/Int32"
        assert sub.name == "cmd"

        # ROS2 delivers a message → bridge must emit a data frame on topic 12.
        sub.on_message(_FakeMessage(data=99))
        _drive(loop)
        [df] = _read_frames(parser, device_fd)
        assert df.msg_id == 12
        conv = converters.get("std_msgs/msg/Int32")
        assert conv is not None
        assert conv.unpack(df.payload) == 99

        # Several messages in a row arrive in order.
        for v in (1, -2, 1_000_000):
            sub.on_message(_FakeMessage(data=v))
        _drive(loop)
        frames = _read_frames(parser, device_fd)
        values = [conv.unpack(f.payload) for f in frames if f.msg_id == 12]
        assert values == [1, -2, 1_000_000]
    finally:
        os.close(device_fd)
        bridge_t.close()


def test_subscribe_string_roundtrips_through_converter() -> None:
    sub_factory = _SubFactory()
    bridge_t, device_fd = PtyTransport.open_pair()
    loop = BridgeLoop(
        transport=bridge_t,
        publisher_factory=lambda *a, **k: None,
        subscription_factory=sub_factory,
    )
    parser = FrameParser()

    try:
        hello = Hello(
            proto_ver=1,
            device_id=b"\x30" * DEVICE_ID_LEN,
            fw_hash=b"\x40" * FW_HASH_LEN,
            max_payload=512,
        )
        os.write(device_fd, encode_frame(0, CONTROL_MSG_ID, hello.encode()))
        _drive(loop)
        _read_frames(parser, device_fd)

        adv = Advertise(
            topic_id=4,
            direction=Direction.SUBSCRIBE,
            type_str="std_msgs/msg/String",
            name="greeting",
        )
        os.write(device_fd, encode_frame(1, CONTROL_MSG_ID, adv.encode()))
        _drive(loop)
        _read_frames(parser, device_fd)

        sub = sub_factory.created[0]
        sub.on_message(_FakeMessage(data="hello, esp32"))
        _drive(loop)
        [df] = _read_frames(parser, device_fd)
        conv = converters.get("std_msgs/msg/String")
        assert conv is not None
        assert df.msg_id == 4
        assert conv.unpack(df.payload) == "hello, esp32"
    finally:
        os.close(device_fd)
        bridge_t.close()


def test_subscription_is_destroyed_on_session_reset() -> None:
    sub_factory = _SubFactory()
    bridge_t, device_fd = PtyTransport.open_pair()
    loop = BridgeLoop(
        transport=bridge_t,
        publisher_factory=lambda *a, **k: None,
        subscription_factory=sub_factory,
    )
    parser = FrameParser()

    try:
        hello = Hello(
            proto_ver=1,
            device_id=b"\x50" * DEVICE_ID_LEN,
            fw_hash=b"\x60" * FW_HASH_LEN,
            max_payload=512,
        )
        os.write(device_fd, encode_frame(0, CONTROL_MSG_ID, hello.encode()))
        _drive(loop)
        _read_frames(parser, device_fd)
        adv = Advertise(
            topic_id=5,
            direction=Direction.SUBSCRIBE,
            type_str="std_msgs/msg/Int32",
            name="cmd",
        )
        os.write(device_fd, encode_frame(1, CONTROL_MSG_ID, adv.encode()))
        _drive(loop)
        _read_frames(parser, device_fd)
        sub = sub_factory.created[0]
        assert not sub.destroyed

        # Simulate device reconnect: fresh HELLO. Bridge must tear
        # down the old subscription.
        os.write(device_fd, encode_frame(2, CONTROL_MSG_ID, hello.encode()))
        _drive(loop)
        _read_frames(parser, device_fd)
        assert sub.destroyed
    finally:
        os.close(device_fd)
        bridge_t.close()
