# 0006 — Payload conversion at the bridge

- Status: accepted
- Date: 2026-05-13

## Context and problem

The firmware sends and receives raw byte payloads. ROS2 sends and
receives typed messages. Something has to translate. The two obvious
ends of the spectrum:

- **Firmware emits CDR.** Smallest bridge code; firmware now knows the
  serialization format DDS uses. Violates ADR-0001.
- **Bridge runs full type-aware serialization.** Firmware stays dumb,
  but the bridge needs to know how each ROS2 type maps to a packed
  byte layout.

## Decision

The bridge owns a small registry of per-type converters. Each
converter knows:

- the ROS2 type string (e.g. `std_msgs/msg/Int32`)
- a function `bytes -> message instance` for device → ROS2 direction
- a function `message instance -> bytes` for ROS2 → device direction

The packed format is the simplest reasonable little-endian layout: an
`int32` is 4 bytes; a `String` is a `uint32` length followed by UTF-8
bytes; arrays are `uint32` count followed by elements. This is
deliberately *not* CDR — it is documented, small, and matches what an
embedded developer would write by hand.

Adding a type means adding a converter in
`ros2-bridge/rosserial2/converters.py`. An advertise for an unknown
type is rejected with a `LOG` frame; the device is expected to choose
a supported type or update its firmware.

M3 supports `std_msgs/msg/Int32` only. Each subsequent milestone adds
the converters that example apps need; we do **not** front-load a
catalog.

## Consequences

- Firmware stays the simplest possible: pack ints little-endian,
  prefix strings with their length. Anyone reading
  `docs/wire-protocol.md` and `converters.py` can write a publisher in
  an afternoon.
- Adding a non-trivial type (`sensor_msgs/Image`, `nav_msgs/Odometry`)
  requires a converter and a test. Acceptable: those types deserve
  thought, not auto-generation.
- We never debug a CDR mismatch on the device. If bytes match the
  converter's expectation, they round-trip.
