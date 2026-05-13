# 0003 — Simplicity charter

- Status: accepted
- Date: 2026-05-13

## Context and problem

The product, end to end, is: plug in an ESP32, click Flash in Chrome, the
device appears as a ROS2 node. Anything that doesn't move that sentence
forward is a distraction. We need a written rule we can point at when a PR
starts to grow.

## Decision

The following are explicitly **not** in scope and any PR adding them needs an
ADR that overrides this one:

- Action servers, full parameter-server bridging, services beyond a minimal
  request/response.
- TLS, authentication, or replay protection on the wire.
- Multi-MCU clustering on a single transport.
- Fragmentation, compression, or QoS-on-the-wire.
- Configuration UIs beyond what the flasher and a serial console offer.
- Anything justified only as "micro-ROS has it." Parity is not a reason.

The following are load-bearing and may not be cut without an ADR:

- The dumb-firmware / smart-bridge split (ADR-0001).
- The wire format (ADR-0002).
- Property-based testing of the codec on both sides.
- The browser flasher as the primary install path.

## Consequences

When in doubt, ship less.
