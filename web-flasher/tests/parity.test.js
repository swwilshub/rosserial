// Cross-language parity: the JS codec must agree with the Python and
// C++ codecs byte-for-byte on the corpus checked into the bridge.
//
// The corpus is generated from Python (rosserial2.codec) with a fixed
// seed; regeneration is an explicit task (ADR-0004). If this test
// fails, either the JS codec drifted or the corpus is stale — never
// both at once.

import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { FrameParser, encodeFrame } from "../js/codec.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CORPUS = path.resolve(__dirname, "../../ros2-bridge/tests/corpus");

function parseRecords(bytes) {
    const out = [];
    let i = 0;
    while (i < bytes.length) {
        assert.ok(bytes.length - i >= 4, "truncated records");
        const seq = bytes[i++];
        const msgId = bytes[i++];
        const len = bytes[i] | (bytes[i + 1] << 8);
        i += 2;
        assert.ok(bytes.length - i >= len, "truncated payload");
        const payload = bytes.slice(i, i + len);
        i += len;
        out.push({ seq, msgId, payload });
    }
    return out;
}

test("corpus: JS decoder agrees with Python on every frame", async () => {
    const records = parseRecords(
        new Uint8Array(await readFile(path.join(CORPUS, "wire_v1_records.bin")))
    );
    const frames = new Uint8Array(await readFile(path.join(CORPUS, "wire_v1_frames.bin")));
    assert.equal(records.length, 256);

    const parser = new FrameParser();
    const got = parser.feed(frames);
    assert.equal(parser.errors, 0);
    assert.equal(got.length, records.length);
    for (let i = 0; i < records.length; i++) {
        assert.equal(got[i].seq, records[i].seq, `record ${i} seq`);
        assert.equal(got[i].msgId, records[i].msgId, `record ${i} msgId`);
        assert.equal(got[i].payload.length, records[i].payload.length,
            `record ${i} payload length`);
        for (let j = 0; j < records[i].payload.length; j++) {
            assert.equal(got[i].payload[j], records[i].payload[j],
                `record ${i} byte ${j}`);
        }
    }
});

test("corpus: JS encoder reproduces Python frame bytes exactly", async () => {
    const records = parseRecords(
        new Uint8Array(await readFile(path.join(CORPUS, "wire_v1_records.bin")))
    );
    const frames = new Uint8Array(await readFile(path.join(CORPUS, "wire_v1_frames.bin")));
    const rebuilt = [];
    let total = 0;
    for (const r of records) {
        const enc = encodeFrame(r.seq, r.msgId, r.payload);
        rebuilt.push(enc);
        total += enc.length;
    }
    const merged = new Uint8Array(total);
    let off = 0;
    for (const chunk of rebuilt) {
        merged.set(chunk, off);
        off += chunk.length;
    }
    assert.equal(merged.length, frames.length, "rebuilt size differs");
    for (let i = 0; i < merged.length; i++) {
        assert.equal(merged[i], frames[i], `byte ${i}`);
    }
});

test("golden files decode in JS too", async () => {
    const goldenDir = path.resolve(__dirname, "../../ros2-bridge/tests/golden");
    const cases = [
        { file: "empty_payload.bin", seq: 0, msgId: 1, len: 0 },
        { file: "ascii_payload.bin", seq: 42, msgId: 7, len: 17 },
        { file: "max_payload.bin", seq: 255, msgId: 255, len: 512 },
    ];
    for (const c of cases) {
        const bytes = new Uint8Array(await readFile(path.join(goldenDir, c.file)));
        const parser = new FrameParser();
        const got = parser.feed(bytes);
        assert.equal(got.length, 1, `${c.file}: frame count`);
        assert.equal(got[0].seq, c.seq, `${c.file}: seq`);
        assert.equal(got[0].msgId, c.msgId, `${c.file}: msgId`);
        assert.equal(got[0].payload.length, c.len, `${c.file}: payload length`);
    }
});
