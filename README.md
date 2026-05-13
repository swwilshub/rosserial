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
| M2        | Firmware codec on the linux target, in CI     | next  |
| M3        | First bring-up: ESP32-S3 publisher            | …     |
| M4        | Subscriber + reconnect + WiFi                 | …     |
| M5        | Web flasher pipeline end-to-end               | …     |
| M6        | ESP-NOW + multi-device demo                   | …     |

## Quick start (M1, host only)

```
make install-bridge
make test
```

## Documents

- `docs/adr/0001-architecture-split.md` — dumb firmware, smart bridge
- `docs/adr/0002-wire-protocol-v1.md` — framing, CRC, resync
- `docs/adr/0003-simplicity-charter.md` — what we don't build
- `docs/wire-protocol.md` — implementer reference
