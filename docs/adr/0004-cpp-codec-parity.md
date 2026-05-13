# 0004 — C++ codec parity strategy

- Status: accepted
- Date: 2026-05-13

## Context and problem

The wire protocol must be encoded and decoded identically by Python on
the host and C++ on the device. Drift between the two codecs is the
single most likely way for this project to silently break, and it is
the failure mode hardest to debug from the outside. We want a CI gate
that fails the build the moment either side disagrees with the wire.

## Options considered

### Option A — Single IDL with codegen for both sides

A schema language and two backends. Powerful, but pulls in a generator,
a build-time dep, and tooling we have to maintain forever.

### Option B — Hand-written codecs, cross-language byte corpus

Each side has a hand-written codec — Python in `rosserial2/codec.py`,
C++ in `esp32-firmware/components/rosserial2_codec/include/.../codec.hpp`.
The Python side generates a binary corpus (golden frames plus
Hypothesis-derived random vectors) and the C++ side decodes that corpus
and verifies the expected fields. The C++ side re-encodes the decoded
fields and verifies byte-for-byte equality with the corpus.

### Option C — Run both codecs through a fuzzer side-by-side

More powerful for finding drift, but requires building C++ from Python
or vice versa. Too much machinery for M2.

## Decision

Option B. The Python codec is the source of truth for the wire format.
The C++ codec is treated like any other consumer of that format. The
corpus file (`tests/corpus/wire_v1.bin` plus a manifest) is generated
deterministically by Python (fixed seed) and checked in. Re-generating
it is an explicit task with the same rules as regenerating golden
frames: only on a wire-version change.

This sidesteps a codegen pipeline entirely without sacrificing the
parity guarantee.

## Consequences

- Two codec implementations live in the repo. They are tiny enough that
  this is acceptable.
- Any change to either side is force-detected by the parity test.
- A future v2 wire bump means regenerating the corpus alongside the
  ADR — the regeneration commit is the audit trail.
- We avoid every question of "which IDL?" — none.
