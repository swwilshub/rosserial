"""Control-plane opcode codec.

Control frames are frames whose ``msg_id`` is 0. The payload begins
with a one-byte opcode followed by an opcode-specific body. See
``docs/wire-protocol.md`` for the table.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

DEVICE_ID_LEN = 16
FW_HASH_LEN = 20


class Opcode(IntEnum):
    HELLO = 0x01
    HELLO_ACK = 0x02
    ADVERTISE = 0x03
    ADVERTISE_ACK = 0x04
    PING = 0x05
    PONG = 0x06
    LOG = 0x07
    BYE = 0xFF


class Direction(IntEnum):
    PUBLISH = 0
    SUBSCRIBE = 1


class ControlError(ValueError):
    """Raised when a control payload cannot be parsed or built."""


# --- HELLO -----------------------------------------------------------


@dataclass(frozen=True)
class Hello:
    proto_ver: int
    device_id: bytes  # exactly DEVICE_ID_LEN bytes
    fw_hash: bytes  # exactly FW_HASH_LEN bytes
    max_payload: int

    def __post_init__(self) -> None:
        if not 0 <= self.proto_ver <= 0xFF:
            raise ControlError(f"proto_ver out of range: {self.proto_ver}")
        if len(self.device_id) != DEVICE_ID_LEN:
            raise ControlError(f"device_id must be {DEVICE_ID_LEN} bytes")
        if len(self.fw_hash) != FW_HASH_LEN:
            raise ControlError(f"fw_hash must be {FW_HASH_LEN} bytes")
        if not 0 <= self.max_payload <= 0xFFFF:
            raise ControlError(f"max_payload out of range: {self.max_payload}")

    def encode(self) -> bytes:
        return (
            bytes([Opcode.HELLO, self.proto_ver])
            + self.device_id
            + self.fw_hash
            + self.max_payload.to_bytes(2, "little")
        )


def _decode_hello(body: bytes) -> Hello:
    expected = 1 + DEVICE_ID_LEN + FW_HASH_LEN + 2
    if len(body) != expected:
        raise ControlError(f"HELLO body length: got {len(body)}, expected {expected}")
    proto_ver = body[0]
    off = 1
    device_id = body[off : off + DEVICE_ID_LEN]
    off += DEVICE_ID_LEN
    fw_hash = body[off : off + FW_HASH_LEN]
    off += FW_HASH_LEN
    max_payload = int.from_bytes(body[off : off + 2], "little")
    return Hello(
        proto_ver=proto_ver,
        device_id=bytes(device_id),
        fw_hash=bytes(fw_hash),
        max_payload=max_payload,
    )


# --- HELLO_ACK -------------------------------------------------------


@dataclass(frozen=True)
class HelloAck:
    proto_ver: int
    accepted: int
    session_id: int

    def __post_init__(self) -> None:
        if not 0 <= self.proto_ver <= 0xFF:
            raise ControlError(f"proto_ver out of range: {self.proto_ver}")
        if not 0 <= self.accepted <= 0xFF:
            raise ControlError(f"accepted out of range: {self.accepted}")
        if not 0 <= self.session_id <= 0xFFFFFFFF:
            raise ControlError(f"session_id out of range: {self.session_id}")

    def encode(self) -> bytes:
        return (
            bytes([Opcode.HELLO_ACK, self.proto_ver, self.accepted])
            + self.session_id.to_bytes(4, "little")
        )


def _decode_hello_ack(body: bytes) -> HelloAck:
    if len(body) != 6:
        raise ControlError(f"HELLO_ACK body length: got {len(body)}, expected 6")
    return HelloAck(
        proto_ver=body[0],
        accepted=body[1],
        session_id=int.from_bytes(body[2:6], "little"),
    )


# --- ADVERTISE -------------------------------------------------------


@dataclass(frozen=True)
class Advertise:
    topic_id: int
    direction: Direction
    type_str: str  # ROS2 canonical, e.g. "std_msgs/msg/String"
    name: str

    def __post_init__(self) -> None:
        if not 1 <= self.topic_id <= 0xFF:
            raise ControlError(f"topic_id must be 1..255, got {self.topic_id}")
        if not 0 <= int(self.direction) <= 1:
            raise ControlError(f"direction invalid: {self.direction}")
        type_bytes = self.type_str.encode("utf-8")
        name_bytes = self.name.encode("utf-8")
        if len(type_bytes) > 0xFF:
            raise ControlError("type_str too long (>255 bytes)")
        if len(name_bytes) > 0xFF:
            raise ControlError("name too long (>255 bytes)")
        if not type_bytes:
            raise ControlError("type_str must not be empty")
        if not name_bytes:
            raise ControlError("name must not be empty")

    def encode(self) -> bytes:
        type_bytes = self.type_str.encode("utf-8")
        name_bytes = self.name.encode("utf-8")
        return (
            bytes(
                [
                    Opcode.ADVERTISE,
                    self.topic_id,
                    int(self.direction),
                    len(type_bytes),
                ]
            )
            + type_bytes
            + bytes([len(name_bytes)])
            + name_bytes
        )


def _decode_advertise(body: bytes) -> Advertise:
    if len(body) < 4:
        raise ControlError(f"ADVERTISE body too short: {len(body)}")
    topic_id = body[0]
    direction = body[1]
    if direction not in (0, 1):
        raise ControlError(f"ADVERTISE bad direction: {direction}")
    type_len = body[2]
    off = 3
    if len(body) < off + type_len + 1:
        raise ControlError("ADVERTISE truncated in type_str")
    type_str = body[off : off + type_len].decode("utf-8")
    off += type_len
    name_len = body[off]
    off += 1
    if len(body) != off + name_len:
        raise ControlError(
            f"ADVERTISE size mismatch: trailing {len(body) - (off + name_len)} bytes"
        )
    name = body[off : off + name_len].decode("utf-8")
    return Advertise(
        topic_id=topic_id,
        direction=Direction(direction),
        type_str=type_str,
        name=name,
    )


# --- ADVERTISE_ACK ---------------------------------------------------


@dataclass(frozen=True)
class AdvertiseAck:
    topic_id: int
    accepted: int

    def __post_init__(self) -> None:
        if not 1 <= self.topic_id <= 0xFF:
            raise ControlError(f"topic_id must be 1..255, got {self.topic_id}")
        if not 0 <= self.accepted <= 0xFF:
            raise ControlError(f"accepted out of range: {self.accepted}")

    def encode(self) -> bytes:
        return bytes([Opcode.ADVERTISE_ACK, self.topic_id, self.accepted])


def _decode_advertise_ack(body: bytes) -> AdvertiseAck:
    if len(body) != 2:
        raise ControlError(f"ADVERTISE_ACK body length: got {len(body)}, expected 2")
    return AdvertiseAck(topic_id=body[0], accepted=body[1])


# --- PING / PONG -----------------------------------------------------


@dataclass(frozen=True)
class Ping:
    nonce: int

    def __post_init__(self) -> None:
        if not 0 <= self.nonce <= 0xFFFFFFFF:
            raise ControlError(f"nonce out of range: {self.nonce}")

    def encode(self) -> bytes:
        return bytes([Opcode.PING]) + self.nonce.to_bytes(4, "little")


@dataclass(frozen=True)
class Pong:
    nonce: int

    def __post_init__(self) -> None:
        if not 0 <= self.nonce <= 0xFFFFFFFF:
            raise ControlError(f"nonce out of range: {self.nonce}")

    def encode(self) -> bytes:
        return bytes([Opcode.PONG]) + self.nonce.to_bytes(4, "little")


def _decode_ping(body: bytes) -> Ping:
    if len(body) != 4:
        raise ControlError(f"PING body length: got {len(body)}, expected 4")
    return Ping(nonce=int.from_bytes(body, "little"))


def _decode_pong(body: bytes) -> Pong:
    if len(body) != 4:
        raise ControlError(f"PONG body length: got {len(body)}, expected 4")
    return Pong(nonce=int.from_bytes(body, "little"))


# --- LOG -------------------------------------------------------------


@dataclass(frozen=True)
class Log:
    level: int
    message: str

    def __post_init__(self) -> None:
        if not 0 <= self.level <= 0xFF:
            raise ControlError(f"level out of range: {self.level}")

    def encode(self) -> bytes:
        return bytes([Opcode.LOG, self.level]) + self.message.encode("utf-8")


def _decode_log(body: bytes) -> Log:
    if len(body) < 1:
        raise ControlError("LOG body too short")
    return Log(level=body[0], message=body[1:].decode("utf-8", errors="replace"))


# --- BYE -------------------------------------------------------------


@dataclass(frozen=True)
class Bye:
    reason: int

    def __post_init__(self) -> None:
        if not 0 <= self.reason <= 0xFF:
            raise ControlError(f"reason out of range: {self.reason}")

    def encode(self) -> bytes:
        return bytes([Opcode.BYE, self.reason])


def _decode_bye(body: bytes) -> Bye:
    if len(body) != 1:
        raise ControlError(f"BYE body length: got {len(body)}, expected 1")
    return Bye(reason=body[0])


# --- dispatch --------------------------------------------------------

ControlMessage = Hello | HelloAck | Advertise | AdvertiseAck | Ping | Pong | Log | Bye

_DECODERS = {
    Opcode.HELLO: _decode_hello,
    Opcode.HELLO_ACK: _decode_hello_ack,
    Opcode.ADVERTISE: _decode_advertise,
    Opcode.ADVERTISE_ACK: _decode_advertise_ack,
    Opcode.PING: _decode_ping,
    Opcode.PONG: _decode_pong,
    Opcode.LOG: _decode_log,
    Opcode.BYE: _decode_bye,
}


def decode_control(payload: bytes) -> ControlMessage:
    """Decode a control-frame payload (opcode byte + body)."""
    if not payload:
        raise ControlError("empty control payload")
    op = payload[0]
    try:
        opcode = Opcode(op)
    except ValueError as exc:
        raise ControlError(f"unknown opcode: {op:#04x}") from exc
    decoder = _DECODERS[opcode]
    return decoder(payload[1:])


def encode_control(msg: ControlMessage) -> bytes:
    """Encode a control message to a frame payload."""
    return msg.encode()
