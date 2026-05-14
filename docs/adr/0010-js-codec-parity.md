# 0010 — JS codec parity

- Status: accepted
- Date: 2026-05-13

## Context and problem

The web flasher's console drives the wire protocol from the browser.
That means a JavaScript implementation of the codec — the third one
after Python and C++. Drift between any two implementations is a
debugging tax we already paid for in ADR-0004; we extend the same
strategy to a third corner.

## Decision

`web-flasher/js/codec.js` is a small ES module that mirrors
`rosserial2/codec.py` exactly: same constants, same frame layout,
same one-byte-rewind `FrameParser`. Same bitwise IEEE 802.3 CRC32
implementation (no tables — the JS engine is fast enough).

The cross-language corpus checked into
`ros2-bridge/tests/corpus/wire_v1_{records,frames}.bin` is the
source of truth. The JS test suite reads the same bytes and asserts:

1. The JS decoder produces the same `(seq, msg_id, payload)` for
   every frame in `wire_v1_frames.bin`.
2. The JS encoder, given the records, reproduces
   `wire_v1_frames.bin` byte-for-byte.

These tests live alongside the JS code under
`web-flasher/tests/` and run on Node (≥20, for the built-in
`node:test` runner). No JS test framework dependency.

## Consequences

- Three codecs, one corpus, one source of truth on the wire.
- The JS codec is read-only as far as the wire protocol is
  concerned: tightening framing requires regenerating the corpus,
  same as the C++ side.
- Browser-only features (WebSerial, esptool-js) stay isolated in
  separate modules so the codec module is testable under Node.
