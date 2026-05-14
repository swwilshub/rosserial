# 0008 — Reconnect as a first-class path

- Status: accepted
- Date: 2026-05-13

## Context and problem

Cables wiggle. WiFi flaps. Boards reboot. The bridge has to survive
all of those without operator intervention. The simplicity charter
(ADR-0003) says reconnect is a first-class state, not an error path.

## Decision

Two layers:

1. **Session reset** (already in M3). On any `TransportError` during
   read or write, the loop drops the current `Session`, clears the
   topic table and publisher map, and arms a fresh `Session` waiting
   for a new `HELLO`. A fresh `HELLO` from the device is also the
   reconnect trigger from the device side: it always resets state.

2. **Transport reopen** (new in M4). A `ReconnectingTransport`
   wrapper opens the underlying transport on demand, surfaces a
   single `TransportError` on failure (which the loop catches),
   then on the next `read()` call retries with capped exponential
   backoff (0.5s → 1s → 2s → ... up to 8s). The wrapper logs each
   reopen attempt.

Reconnect is what happens when a serial port disappears and comes
back, when a TCP socket EOFs, or when the device reboots. All three
flow through the same path: transport error → session reset → next
read reopens → device sends fresh HELLO → topics are rebuilt.

## Consequences

- No special "reconnect" code path inside the session or the codec.
  The set of states stays small.
- The supervisor adds a small amount of `time.sleep()` to the loop
  on failure; tests pass a `sleep` injection to keep them fast.
- Outbound frames queued before a transport error are dropped on
  reset. The device will retransmit advertises on its next HELLO,
  and ROS2 subscribers will deliver fresh messages on resume — no
  data is owed.
