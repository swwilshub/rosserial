"""Regenerate the cross-language corpus consumed by the C++ tests.

The corpus is a single binary file plus a manifest. Each record:

    [u16 seq+msg_id packed][u16 payload_len][payload bytes]

Specifically:

    record = u8 seq | u8 msg_id | u16 payload_len (LE) | payload

Records concatenated; the manifest stores the count.

Run from the repo root:

    python ros2-bridge/tests/corpus/regenerate.py

This is intentionally outside pytest. Regenerating is a wire-format
event (ADR-required), not a CI step.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from rosserial2.codec import MAX_PAYLOAD, encode_frame

HERE = Path(__file__).resolve().parent
SEED = 0xC0FFEE
N_RECORDS = 256


def main() -> None:
    rng = random.Random(SEED)
    records: list[tuple[int, int, bytes]] = []
    # Deterministic, exhaustive-feeling: a few hand-picked edge cases
    # plus randomized vectors.
    records.append((0, 1, b""))
    records.append((255, 0, b""))
    records.append((1, 7, b"\xaa\x55" * 50))  # payload masquerading as sync
    records.append((42, 9, bytes(range(256))[:200]))
    records.append((255, 255, bytes(range(256)) * 2))  # MAX_PAYLOAD
    for _ in range(N_RECORDS - len(records)):
        seq = rng.randint(0, 255)
        msg_id = rng.randint(0, 255)
        n = rng.randint(0, MAX_PAYLOAD)
        payload = bytes(rng.randint(0, 255) for _ in range(n))
        records.append((seq, msg_id, payload))

    out_records = bytearray()
    out_frames = bytearray()
    expectations: list[dict] = []
    for seq, msg_id, payload in records:
        out_records.append(seq)
        out_records.append(msg_id)
        out_records += len(payload).to_bytes(2, "little")
        out_records += payload
        encoded = encode_frame(seq, msg_id, payload)
        out_frames += encoded
        expectations.append(
            {
                "seq": seq,
                "msg_id": msg_id,
                "payload_len": len(payload),
                "frame_len": len(encoded),
            }
        )

    (HERE / "wire_v1_records.bin").write_bytes(bytes(out_records))
    (HERE / "wire_v1_frames.bin").write_bytes(bytes(out_frames))
    manifest = {
        "version": 1,
        "seed": SEED,
        "count": len(records),
        "max_payload": MAX_PAYLOAD,
        "records": expectations,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(
        f"wrote {len(records)} records: "
        f"{len(out_records)} bytes records, {len(out_frames)} bytes frames"
    )


if __name__ == "__main__":
    main()
