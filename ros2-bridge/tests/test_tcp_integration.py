"""TCP transport integration test.

The bridge binds an ephemeral TCP port; a synthetic "device" client
connects and runs the same handshake the pty test exercises. This
proves the wire protocol is transport-agnostic.
"""

from __future__ import annotations

import socket
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
from rosserial2.transports.tcp import TcpServerTransport

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="TCP test relies on POSIX socket semantics",
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
        rec = _Recorder(type_str, name)
        self.created.append(rec)
        return rec


def _drive(loop: BridgeLoop, deadline_s: float = 1.5) -> None:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if not loop.run_once():
            return


def _read_frames(parser: FrameParser, sock: socket.socket, deadline_s: float = 1.5):
    end = time.monotonic() + deadline_s
    sock.settimeout(0.05)
    while time.monotonic() < end:
        try:
            data = sock.recv(4096)
        except TimeoutError:
            data = b""
        if data:
            frames = parser.feed(data)
            if frames:
                return frames
    raise AssertionError("timed out waiting for a frame from the bridge")


def test_tcp_handshake_and_publish() -> None:
    factory = _Factory()
    server = TcpServerTransport(host="127.0.0.1", port=0)
    loop = BridgeLoop(transport=server, publisher_factory=factory)
    parser = FrameParser()

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect(("127.0.0.1", server.bound_port))
        # Let the bridge accept.
        _drive(loop, deadline_s=0.2)

        hello = Hello(
            proto_ver=1,
            device_id=b"\x70" * DEVICE_ID_LEN,
            fw_hash=b"\x80" * FW_HASH_LEN,
            max_payload=512,
        )
        client.sendall(encode_frame(0, CONTROL_MSG_ID, hello.encode()))
        _drive(loop)
        [hf] = _read_frames(parser, client)
        assert isinstance(decode_control(hf.payload), HelloAck)

        adv = Advertise(
            topic_id=9,
            direction=Direction.PUBLISH,
            type_str="std_msgs/msg/Int32",
            name="ticker",
        )
        client.sendall(encode_frame(1, CONTROL_MSG_ID, adv.encode()))
        _drive(loop)
        [af] = _read_frames(parser, client)
        ack = decode_control(af.payload)
        assert isinstance(ack, AdvertiseAck) and ack.accepted == 1

        conv = converters.get("std_msgs/msg/Int32")
        assert conv is not None
        for i, v in enumerate([7, 8, 9], start=2):
            client.sendall(encode_frame(i, 9, conv.pack(v)))
        _drive(loop)
        assert factory.created[0].published == [7, 8, 9]
    finally:
        client.close()
        server.close()


def test_tcp_client_disconnect_resets_session() -> None:
    factory = _Factory()
    server = TcpServerTransport(host="127.0.0.1", port=0)
    loop = BridgeLoop(transport=server, publisher_factory=factory)
    parser = FrameParser()

    try:
        # First connection.
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", server.bound_port))
        _drive(loop, 0.2)
        hello = Hello(
            proto_ver=1,
            device_id=b"\x10" * DEVICE_ID_LEN,
            fw_hash=b"\x20" * FW_HASH_LEN,
            max_payload=512,
        )
        client.sendall(encode_frame(0, CONTROL_MSG_ID, hello.encode()))
        _drive(loop)
        _read_frames(parser, client)
        assert loop.session.state.name == "READY"

        # Client goes away.
        client.close()
        _drive(loop, 0.3)
        # Bridge should have reset its session — a fresh one is waiting
        # for HELLO again.
        assert loop.session.state.name == "AWAIT_HELLO"

        # Second connection comes in — handshake works again.
        client2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client2.connect(("127.0.0.1", server.bound_port))
        _drive(loop, 0.2)
        client2.sendall(encode_frame(0, CONTROL_MSG_ID, hello.encode()))
        _drive(loop)
        parser2 = FrameParser()
        [hf] = _read_frames(parser2, client2)
        assert isinstance(decode_control(hf.payload), HelloAck)
        client2.close()
    finally:
        server.close()
