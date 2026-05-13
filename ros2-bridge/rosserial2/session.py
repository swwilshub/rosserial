"""Session state machine skeleton.

The session owns the topic table, the per-direction sequence numbers,
and the handshake lifecycle. It does *not* own a transport or rclpy:
those are injected by the bridge node so the session can be tested
in isolation.

This is M1 scope: the state machine is defined and the codec wiring
is in place. Actual ROS2 publish/subscribe wiring lands in M3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from rosserial2.codec import CONTROL_MSG_ID, Frame, encode_frame
from rosserial2.control import (
    Advertise,
    AdvertiseAck,
    Bye,
    Direction,
    Hello,
    HelloAck,
    Ping,
    Pong,
    decode_control,
)


class SessionState(Enum):
    IDLE = auto()
    AWAIT_HELLO = auto()
    READY = auto()
    CLOSED = auto()


@dataclass
class TopicEntry:
    topic_id: int
    direction: Direction
    type_str: str
    name: str


@dataclass
class Session:
    """In-process session: pure state, no I/O."""

    proto_ver: int = 1
    state: SessionState = SessionState.AWAIT_HELLO
    session_id: int = 0
    device_id: bytes = b""
    fw_hash: bytes = b""
    device_max_payload: int = 0
    # tx side: next outgoing seq.
    _tx_seq: int = 0
    # rx side: last seq we observed (None ⇒ no data yet).
    _rx_seq_last: int | None = None
    rx_seq_skips: int = 0
    topics: dict[int, TopicEntry] = field(default_factory=dict)
    # Frames the caller should write to the transport.
    _outbox: list[bytes] = field(default_factory=list)

    # --- public API ---------------------------------------------------

    def on_frame(self, frame: Frame) -> None:
        """Feed a decoded frame into the session."""
        if self._rx_seq_last is not None:
            expected = (self._rx_seq_last + 1) & 0xFF
            if frame.seq != expected:
                self.rx_seq_skips += 1
        self._rx_seq_last = frame.seq

        if frame.msg_id == CONTROL_MSG_ID:
            self._on_control(frame.payload)
        else:
            self._on_data(frame.msg_id, frame.payload)

    def drain_outbox(self) -> list[bytes]:
        out = self._outbox
        self._outbox = []
        return out

    def close(self, reason: int = 0) -> None:
        if self.state is not SessionState.CLOSED:
            self._send_control(Bye(reason=reason).encode())
        self.state = SessionState.CLOSED

    # --- control handlers --------------------------------------------

    def _on_control(self, payload: bytes) -> None:
        msg = decode_control(payload)
        if isinstance(msg, Hello):
            self._on_hello(msg)
        elif isinstance(msg, Advertise):
            self._on_advertise(msg)
        elif isinstance(msg, Ping):
            self._send_control(Pong(nonce=msg.nonce).encode())
        elif isinstance(msg, Bye):
            self.state = SessionState.CLOSED
        # HelloAck / AdvertiseAck / Pong / Log are device-bound or
        # informational from the device side; bridge ignores them.

    def _on_hello(self, msg: Hello) -> None:
        self.device_id = msg.device_id
        self.fw_hash = msg.fw_hash
        self.device_max_payload = msg.max_payload
        # M1: always accept. Sessions are deterministic.
        self.session_id = (self.session_id + 1) & 0xFFFFFFFF
        self.state = SessionState.READY
        self._send_control(
            HelloAck(
                proto_ver=self.proto_ver,
                accepted=1,
                session_id=self.session_id,
            ).encode()
        )

    def _on_advertise(self, msg: Advertise) -> None:
        if self.state is not SessionState.READY:
            self._send_control(AdvertiseAck(topic_id=msg.topic_id, accepted=0).encode())
            return
        self.topics[msg.topic_id] = TopicEntry(
            topic_id=msg.topic_id,
            direction=msg.direction,
            type_str=msg.type_str,
            name=msg.name,
        )
        self._send_control(AdvertiseAck(topic_id=msg.topic_id, accepted=1).encode())

    def _on_data(self, msg_id: int, payload: bytes) -> None:
        # M3 will route to rclpy publishers. M1: drop with a counter so
        # tests can assert the session noticed.
        entry = self.topics.get(msg_id)
        if entry is None:
            self.rx_seq_skips += 0  # placeholder; could add unknown-topic counter
            return
        # No-op for now.

    # --- tx helpers --------------------------------------------------

    def _send_control(self, payload: bytes) -> None:
        self._outbox.append(self._encode(CONTROL_MSG_ID, payload))

    def _encode(self, msg_id: int, payload: bytes) -> bytes:
        seq = self._tx_seq
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        return encode_frame(seq=seq, msg_id=msg_id, payload=payload)
