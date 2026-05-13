"""Session state machine.

Pure state: no transport, no rclpy, no threads. The bridge loop drives
it. Outbound frames are queued; the loop drains and writes them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto

from rosserial2 import converters
from rosserial2.codec import CONTROL_MSG_ID, Frame, encode_frame
from rosserial2.control import (
    Advertise,
    AdvertiseAck,
    Bye,
    Direction,
    Hello,
    HelloAck,
    Log,
    Opcode,
    Ping,
    Pong,
    decode_control,
)


class SessionState(Enum):
    AWAIT_HELLO = auto()
    READY = auto()
    CLOSED = auto()


# Callbacks injected by the bridge loop. They let the session announce
# topic events without taking on rclpy as a dependency.
#
# ``on_advertise``: device announced a topic; return True to accept,
# False to reject. The callback owns the publisher creation.
# ``on_data``: a payload arrived for a known device-publish topic.
OnAdvertise = Callable[["TopicEntry"], bool]
OnData = Callable[["TopicEntry", bytes], None]


@dataclass
class TopicEntry:
    topic_id: int
    direction: Direction
    type_str: str
    name: str


@dataclass
class Session:
    proto_ver: int = 1
    on_advertise: OnAdvertise | None = None
    on_data: OnData | None = None
    state: SessionState = SessionState.AWAIT_HELLO
    session_id: int = 0
    device_id: bytes = b""
    fw_hash: bytes = b""
    device_max_payload: int = 0
    _tx_seq: int = 0
    _rx_seq_last: int | None = None
    rx_seq_skips: int = 0
    topics: dict[int, TopicEntry] = field(default_factory=dict)
    _outbox: list[bytes] = field(default_factory=list)

    # --- API for the bridge loop --------------------------------------

    def on_frame(self, frame: Frame) -> None:
        if self._rx_seq_last is not None:
            expected = (self._rx_seq_last + 1) & 0xFF
            if frame.seq != expected:
                self.rx_seq_skips += 1
        self._rx_seq_last = frame.seq

        if frame.msg_id == CONTROL_MSG_ID:
            self._on_control(frame.payload)
        else:
            self._on_topic_data(frame.msg_id, frame.payload)

    def drain_outbox(self) -> list[bytes]:
        out = self._outbox
        self._outbox = []
        return out

    def send_to_device(self, topic_id: int, payload: bytes) -> None:
        """Queue a data frame to a subscribed-by-device topic."""
        self._outbox.append(self._encode(topic_id, payload))

    def close(self, reason: int = 0) -> None:
        if self.state is not SessionState.CLOSED:
            self._send_control(Bye(reason=reason).encode())
        self.state = SessionState.CLOSED

    # --- control plane ------------------------------------------------

    def _on_control(self, payload: bytes) -> None:
        msg = decode_control(payload)
        if isinstance(msg, Hello):
            self._handle_hello(msg)
        elif isinstance(msg, Advertise):
            self._handle_advertise(msg)
        elif isinstance(msg, Ping):
            self._send_control(Pong(nonce=msg.nonce).encode())
        elif isinstance(msg, Bye):
            self.state = SessionState.CLOSED

    def _handle_hello(self, msg: Hello) -> None:
        # Any HELLO resets the session — that is also the reconnect
        # path (ADR-0002 + ADR-0001).
        self.topics.clear()
        self._rx_seq_last = None
        self.device_id = msg.device_id
        self.fw_hash = msg.fw_hash
        self.device_max_payload = msg.max_payload
        self.session_id = (self.session_id + 1) & 0xFFFFFFFF
        self.state = SessionState.READY
        self._send_control(
            HelloAck(
                proto_ver=self.proto_ver,
                accepted=1,
                session_id=self.session_id,
            ).encode()
        )

    def _handle_advertise(self, msg: Advertise) -> None:
        if self.state is not SessionState.READY:
            self._send_control(AdvertiseAck(topic_id=msg.topic_id, accepted=0).encode())
            return
        if converters.get(msg.type_str) is None:
            self._send_control(AdvertiseAck(topic_id=msg.topic_id, accepted=0).encode())
            self._send_control(
                Log(level=1, message=f"unknown type: {msg.type_str}").encode()
            )
            return
        entry = TopicEntry(
            topic_id=msg.topic_id,
            direction=msg.direction,
            type_str=msg.type_str,
            name=msg.name,
        )
        accepted = True
        if self.on_advertise is not None:
            accepted = bool(self.on_advertise(entry))
        if accepted:
            self.topics[msg.topic_id] = entry
            self._send_control(AdvertiseAck(topic_id=msg.topic_id, accepted=1).encode())
        else:
            self._send_control(AdvertiseAck(topic_id=msg.topic_id, accepted=0).encode())

    # --- topic data ---------------------------------------------------

    def _on_topic_data(self, topic_id: int, payload: bytes) -> None:
        entry = self.topics.get(topic_id)
        if entry is None or entry.direction is not Direction.PUBLISH:
            return
        if self.on_data is not None:
            self.on_data(entry, payload)

    # --- helpers ------------------------------------------------------

    def _send_control(self, payload: bytes) -> None:
        self._outbox.append(self._encode(CONTROL_MSG_ID, payload))

    def _encode(self, msg_id: int, payload: bytes) -> bytes:
        seq = self._tx_seq
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        return encode_frame(seq=seq, msg_id=msg_id, payload=payload)


# Re-exported for callers that want to introspect opcodes.
__all__ = [
    "OnAdvertise",
    "OnData",
    "Opcode",
    "Session",
    "SessionState",
    "TopicEntry",
]
