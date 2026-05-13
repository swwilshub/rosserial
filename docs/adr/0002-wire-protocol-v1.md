# 0002 — Wire protocol v1

- Status: accepted
- Date: 2026-05-13

## Context and problem

We need a frame format that is easy to parse on an ESP32 byte-by-byte in a
state machine, easy to resync after byte loss, and easy to read in a hex dump
during bring-up. It must carry both negotiated topic data and a small
control-plane vocabulary on the same channel.

## Decision

Frame layout, all little-endian:

```
+------+------+--------+--------+-----+--------+--------------+----------+
| 0xAA | 0x55 | LEN_LO | LEN_HI | SEQ | MSG_ID | PAYLOAD ...  |  CRC32   |
+------+------+--------+--------+-----+--------+--------------+----------+
   1      1      1        1       1      1        LEN bytes      4 bytes
```

- **Sync** is `0xAA 0x55`. Two bytes is enough because the CRC catches false
  locks; more would only fight payload bytes for budget.
- **LEN** is `u16` payload length, `0..MAX_PAYLOAD`. `MAX_PAYLOAD = 512` for
  v1. A frame with `LEN > MAX_PAYLOAD` is dropped without consuming the
  candidate sync; the receiver re-scans from the byte after the first sync
  byte.
- **SEQ** is a per-direction monotonic `u8` that wraps at 256. Wrap is fine;
  the receiver only checks for skips.
- **MSG_ID** is `u8`. `0` is the control plane (see ADR-0003 follow-ups for
  the opcode list, currently in `docs/wire-protocol.md`). `1..255` are
  topic IDs assigned during handshake.
- **CRC32** is IEEE 802.3 (poly `0xEDB88320`, init `0xFFFFFFFF`, xorout
  `0xFFFFFFFF`). It covers `LEN_LO` through the last payload byte, inclusive,
  and is transmitted little-endian.

Total per-frame overhead is 10 bytes.

## Resync

The receiver is a state machine: `HUNT → LEN → SEQ → MSG_ID → PAYLOAD → CRC`.
At any failure (bad LEN, bad CRC, transport error) it returns to `HUNT` and
resumes scanning from the byte *after* the first sync byte of the failed
attempt. This guarantees:

- After arbitrary garbage, the next valid frame is locked within
  `garbage_bytes + 10 + LEN` bytes.
- A payload that legally contains `0xAA 0x55` cannot cause a permanent lock:
  the inner candidate either fails LEN-bound or fails CRC, and the scanner
  walks past it.

`N` (the documented resync bound) is `MAX_PAYLOAD + 10` bytes after the last
byte of corruption. This is regression-tested with Hypothesis-generated
prefixes.

## Why CRC32 (not 16, not 8)

The frame is small but the channel is not always close-range serial — WiFi
and ESP-NOW have measurable BER. CRC32 has a vanishingly small undetected
error rate at our payload sizes, the ESP32 has hardware acceleration for it,
and the host cost is irrelevant. The 2 extra bytes vs CRC16 are not worth a
later wire-format break.

## Versioning

A breaking change to framing is a v2 protocol and a new ADR. The version
is communicated only in the `HELLO` control frame, not in every data frame —
data frames must stay tight.

## Consequences

- One hand-written state machine on the MCU. No allocator. No table beyond
  the CRC32 table (1 KB if used; can also be computed bitwise).
- Hex dumps stay readable: `aa 55 ..` jumps out.
- Max payload of 512 bytes is enough for `std_msgs`, IMU, small images at
  low rate, and most sensor topics. Larger payloads would need fragmentation,
  which is deferred to a v1.1 ADR if a real use case arrives.
