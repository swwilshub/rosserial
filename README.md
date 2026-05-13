# rosserial2

A small, boring transport that turns an ESP32 into a ROS2 node. Plug in
the board, click **Flash** in Chrome, and a topic appears.

This is a fresh take on rosserial, scoped to ESP32 + ROS2. It is *not*
micro-ROS: there is no XRCE-DDS on the MCU, no DDS, no agent install.
A Python bridge owns DDS; the device speaks a tight wire protocol.

> The original ROS1 rosserial sources remain in this repository under
> their original directory names (`rosserial_arduino/`, `rosserial_python/`,
> …) and are not maintained as part of this project.

## Layout

```
docs/                  ADRs and the wire protocol spec
ros2-bridge/           Python rclpy bridge (host)
esp32-firmware/        ESP-IDF component (M2+)
web-flasher/           Static WebSerial flasher (M5)
```

## Status

| Milestone | Scope                                         | State |
|-----------|-----------------------------------------------|-------|
| M1        | Wire protocol spec + host codec + tests       | done  |
| M2        | Firmware codec on the linux target, in CI     | done  |
| M3        | First bring-up: ESP32-S3 publisher            | done  |
| M4        | Subscriber + reconnect + WiFi                 | next  |
| M5        | Web flasher pipeline end-to-end               | …     |
| M6        | ESP-NOW + multi-device demo                   | …     |

## Quick start

```
make install-bridge   # one-time: pip install -e ros2-bridge[test,dev]
make test             # runs Python + C++ codec test suites
```

Components individually:

- `make test-bridge` — Python (pytest + Hypothesis)
- `make test-fw` — C++ (CMake + Catch2 v3, fetched on first build)

## Documents

- `docs/adr/0001-architecture-split.md` — dumb firmware, smart bridge
- `docs/adr/0002-wire-protocol-v1.md` — framing, CRC, resync
- `docs/adr/0003-simplicity-charter.md` — what we don't build
- `docs/adr/0004-cpp-codec-parity.md` — how the two codecs stay in step
- `docs/adr/0005-memory-policy.md` — no heap in steady state
- `docs/adr/0006-payload-conversion.md` — bridge owns per-type converters
- `docs/wire-protocol.md` — implementer reference
- `docs/hil-setup.md` — hardware-in-the-loop runner setup
