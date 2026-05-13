# 0001 — Dumb firmware, smart bridge

- Status: accepted
- Date: 2026-05-13

## Context and problem

A basic ESP32 has roughly 320 KB of usable RAM and a single hardware serial
console most users will reach for. micro-ROS bundles XRCE-DDS, RMW shims, and
a static memory pool large enough to hurt on this class of part, and it pushes
the user into colcon and a custom agent install. We want a transport that
keeps firmware boring and pushes everything else to the host.

## Decision

Split the system in two:

- **Firmware** knows: byte layouts of negotiated messages, numeric topic IDs,
  the wire framing, and a small control-plane vocabulary. It does not know
  topic names, ROS2 type strings, QoS profiles, CDR, or DDS.
- **Bridge** is a Python `rclpy` node. It owns DDS, type imports, QoS, and the
  topic-name ↔ topic-ID table. It speaks our wire protocol on one side and
  ROS2 on the other.

Topic ↔ ID negotiation happens at handshake: the device advertises the type
string and a direction; the bridge assigns a numeric ID for the session. The
device only ever sees the ID after that.

## Consequences

- Firmware ports stay small and identical across boards: code that knows DDS
  doesn't exist on the MCU.
- Adding a new ROS2 message type is a host-side change in the common case.
- We accept that the bridge is a required hop. There is no direct DDS path
  from the MCU. This is a deliberate trade for boring firmware.
- micro-ROS feature parity is explicitly a non-goal. If a feature exists only
  because micro-ROS has it, it doesn't justify itself here.
