# 0007 — Subscribe path (ROS2 → device)

- Status: accepted
- Date: 2026-05-13

## Context and problem

A useful node sends *and* receives. The publish path (device → ROS2)
landed in M3. The subscribe path (ROS2 → device) needs to slot in
without growing the wire format or the firmware state machine.

## Decision

Re-use the existing `ADVERTISE` opcode with `direction = Subscribe`.
That advertise tells the bridge: "I want to receive frames whose
`msg_id` equals this `topic_id`, decoded according to this type
string." The bridge then:

1. Looks up a converter for the type string.
2. Creates a ROS2 subscriber on the named topic.
3. On each ROS2 message, packs it via the converter and emits a data
   frame with the negotiated `topic_id` to the device.

No new opcodes. No fan-out: one subscribe per topic. The device-side
state machine treats subscribe-direction topics exactly like
publish-direction topics on receipt: route the payload by `msg_id`.

## Consequences

- The same firmware code that publishes can subscribe by toggling
  `direction` and providing a receive handler keyed on `topic_id`.
  No protocol cost.
- The bridge owns one rclpy subscriber per advertised topic. They
  are torn down on session reset alongside their publisher siblings.
- Back-pressure is the transport's problem: if writes block, the
  loop stalls reads symmetrically. We don't grow a buffer. If a
  real application needs higher throughput, a future ADR can add a
  bounded outbox.
