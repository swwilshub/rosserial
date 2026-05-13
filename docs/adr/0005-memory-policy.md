# 0005 — Memory policy on device

- Status: accepted
- Date: 2026-05-13

## Context and problem

A basic ESP32 has on the order of 320 KB usable RAM. micro-ROS hurts on
this part partly because its memory footprint is generous. We want a
hard rule that lets us prove, in CI, that the firmware does not
allocate during normal operation.

The bridge negotiates topics at handshake, so the device cannot know
its topic table at compile time without forfeiting the dynamic
handshake. We need a rule that admits this without admitting a heap in
the message-publishing path.

## Decision

Two zones:

1. **Boot / handshake.** Allocation is permitted *up to a documented
   ceiling* (`ROSSERIAL2_HANDSHAKE_HEAP_BUDGET`, default 4 KB). The
   handshake builds the topic table and any per-topic resources.
2. **Steady state.** Zero dynamic allocation. The codec, the parser,
   the transport read/write loops, and the publisher dispatch all
   operate on caller-provided buffers and pre-allocated pools.

The C++ codec is header-only and explicitly:

- Uses no `std::vector`, no `std::string`, no `new`, no `malloc`.
- Returns sizes; the caller passes buffers.
- The `FrameParser` owns a single fixed-size buffer
  (`MAX_PAYLOAD + OVERHEAD` bytes) sized at compile time.

CI enforcement (M3+, when the linux-target firmware exists): a
heap-trace harness wraps `malloc`/`free` during a recorded scenario
and fails the build if any allocation occurs after the
handshake-complete event.

## Consequences

- The codec is trivially embeddable: a single header, no runtime.
- Topic count is bounded by the pool size chosen at compile time.
  Default: 16 topics × `MAX_PAYLOAD` payload buffer each. Larger
  applications recompile with a different config.
- We never debug a heap fragmentation issue on the MCU.
