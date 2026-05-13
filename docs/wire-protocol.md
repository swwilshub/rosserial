# rosserial2 wire protocol v1

This document is the implementer's reference. The framing is fixed by
ADR-0002. The control-plane vocabulary is fixed here.

## Frame

```
+------+------+--------+--------+-----+--------+--------------+----------+
| 0xAA | 0x55 | LEN_LO | LEN_HI | SEQ | MSG_ID | PAYLOAD ...  |  CRC32   |
+------+------+--------+--------+-----+--------+--------------+----------+
```

- `LEN`: u16 LE, range `0..512`.
- `SEQ`: u8 monotonic per direction, wraps at 256.
- `MSG_ID`: u8. `0` = control. `1..255` = topic IDs assigned at handshake.
- `CRC32`: IEEE 802.3, computed over `LEN_LO..end of payload`, transmitted LE.

## Control plane (MSG_ID == 0)

Control payloads are `OPCODE (u8) | BODY ...`. Opcodes:

| code | name         | direction      | body |
|------|--------------|----------------|------|
| 0x01 | `HELLO`      | device → bridge| `proto_ver:u8 | device_id:16 | fw_hash:20 | max_payload:u16` |
| 0x02 | `HELLO_ACK`  | bridge → device| `proto_ver:u8 | accepted:u8 | session_id:u32` |
| 0x03 | `ADVERTISE`  | device → bridge| `topic_id:u8 | direction:u8 | type_len:u8 | type_str | name_len:u8 | name_str` |
| 0x04 | `ADVERTISE_ACK` | bridge → device | `topic_id:u8 | accepted:u8` |
| 0x05 | `PING`       | either         | `nonce:u32` |
| 0x06 | `PONG`       | either         | `nonce:u32` |
| 0x07 | `LOG`        | device → bridge| `level:u8 | message_utf8 ...` |
| 0xFF | `BYE`        | either         | `reason:u8` |

`direction` in `ADVERTISE`: `0 = device-publishes`, `1 = device-subscribes`.

`accepted` is a non-zero status code; `0` means rejected. Specific codes are
host-side only and not part of the wire contract.

`type_str` is a ROS2 type string in the canonical form
`<package>/msg/<Name>` (e.g. `std_msgs/msg/String`). Bridge-side import
failures produce a rejected `ADVERTISE_ACK` and a `LOG` line.

Strings are UTF-8 and are not null-terminated. Length prefixes are exact.

## Receiver state machine

```
HUNT  : scan for 0xAA; on hit → SYNC2
SYNC2 : if next == 0x55 → LEN_LO else HUNT (re-test current byte as 0xAA)
LEN_LO: capture
LEN_HI: capture; if LEN > MAX_PAYLOAD → HUNT
SEQ   : capture
MSG_ID: capture
PAYLD : read LEN bytes
CRC0..3: capture; verify; on success → emit frame; always → HUNT
```

On any transport error or any verification failure the state machine returns
to `HUNT`. Resync bound: at most `MAX_PAYLOAD + 10` bytes after the last
corrupted byte. This is regression-tested.

## Session lifecycle

```
device boot
  └→ send HELLO (repeat with backoff until HELLO_ACK)
       └→ for each pub/sub: send ADVERTISE (repeat until ACK)
            └→ steady state: data frames + periodic PING
```

Reconnect (transport drop, bridge restart): device restarts at HELLO. The
bridge treats a new HELLO as a fresh session and discards the previous topic
table.
