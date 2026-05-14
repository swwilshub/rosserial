// Unit tests for the JS codec. Run with: node --test
import test from "node:test";
import assert from "node:assert/strict";
import {
    SYNC,
    HEADER_SIZE,
    OVERHEAD,
    MAX_PAYLOAD,
    FrameError,
    FrameParser,
    crc32,
    decodeFrame,
    encodeFrame,
} from "../js/codec.js";

function bytes(...xs) { return Uint8Array.from(xs); }
function eq(a, b) {
    assert.equal(a.length, b.length, `length: got ${a.length}, want ${b.length}`);
    for (let i = 0; i < a.length; i++) {
        assert.equal(a[i], b[i], `byte ${i}: got ${a[i]}, want ${b[i]}`);
    }
}

test("constants lock the spec", () => {
    assert.equal(SYNC[0], 0xaa);
    assert.equal(SYNC[1], 0x55);
    assert.equal(HEADER_SIZE, 6);
    assert.equal(OVERHEAD, 10);
    assert.equal(MAX_PAYLOAD, 512);
});

test("crc32 matches IEEE 802.3 known vectors", () => {
    // Vectors verified against Python zlib.crc32:
    //   crc32(b"")                 == 0
    //   crc32(b"123456789")        == 0xCBF43926
    //   crc32(b"hello, world")     == 0xFFAB723A
    assert.equal(crc32(new Uint8Array([])), 0);
    const a = new TextEncoder().encode("123456789");
    assert.equal(crc32(a), 0xcbf43926);
    const b = new TextEncoder().encode("hello, world");
    assert.equal(crc32(b), 0xffab723a);
});

test("encode + decode roundtrip — fixed cases", () => {
    const cases = [
        { seq: 0, msgId: 1, payload: bytes() },
        { seq: 42, msgId: 7, payload: new TextEncoder().encode("hello") },
        { seq: 255, msgId: 255, payload: new Uint8Array(MAX_PAYLOAD).fill(0xab) },
    ];
    for (const c of cases) {
        const enc = encodeFrame(c.seq, c.msgId, c.payload);
        const dec = decodeFrame(enc);
        assert.equal(dec.seq, c.seq);
        assert.equal(dec.msgId, c.msgId);
        eq(dec.payload, c.payload);
    }
});

test("randomized roundtrip — 2000 cases", () => {
    // Deterministic LCG so we can reproduce failures.
    let state = 0xc0decafe >>> 0;
    const rand = (n) => {
        state = (state * 1664525 + 1013904223) >>> 0;
        return state % n;
    };
    for (let i = 0; i < 2000; i++) {
        const seq = rand(256);
        const msgId = rand(256);
        const len = rand(MAX_PAYLOAD + 1);
        const payload = new Uint8Array(len);
        for (let j = 0; j < len; j++) payload[j] = rand(256);
        const enc = encodeFrame(seq, msgId, payload);
        const dec = decodeFrame(enc);
        assert.equal(dec.seq, seq, `seq i=${i}`);
        assert.equal(dec.msgId, msgId, `msgId i=${i}`);
        eq(dec.payload, payload);
    }
});

test("encode validates inputs", () => {
    assert.throws(() => encodeFrame(-1, 0, new Uint8Array()), FrameError);
    assert.throws(() => encodeFrame(256, 0, new Uint8Array()), FrameError);
    assert.throws(() => encodeFrame(0, -1, new Uint8Array()), FrameError);
    assert.throws(() => encodeFrame(0, 256, new Uint8Array()), FrameError);
    assert.throws(
        () => encodeFrame(0, 0, new Uint8Array(MAX_PAYLOAD + 1)),
        FrameError,
    );
});

test("decode rejects bad sync, bad CRC, short buffer", () => {
    const buf = encodeFrame(7, 9, bytes(1, 2, 3));
    const bad = buf.slice();
    bad[0] = 0;
    assert.throws(() => decodeFrame(bad), FrameError);
    const corrupt = buf.slice();
    corrupt[corrupt.length - 1] ^= 1;
    assert.throws(() => decodeFrame(corrupt), FrameError);
    assert.throws(() => decodeFrame(bytes(0xaa, 0x55)), FrameError);
});

test("streaming parser — locks onto frame after junk", () => {
    const junk = bytes(0x00, 0xff, 0xaa, 0x55, 0xff, 0xff);  // bad-LEN sync
    const good = encodeFrame(7, 1, new TextEncoder().encode("ok"));
    const stream = new Uint8Array(junk.length + good.length);
    stream.set(junk, 0);
    stream.set(good, junk.length);
    const p = new FrameParser();
    const frames = p.feed(stream);
    assert.equal(frames.length, 1);
    assert.equal(frames[0].seq, 7);
    assert.equal(frames[0].msgId, 1);
    eq(frames[0].payload, new TextEncoder().encode("ok"));
});

test("streaming parser — arbitrary chunking", () => {
    const f1 = encodeFrame(1, 2, new TextEncoder().encode("alpha"));
    const f2 = encodeFrame(3, 4, new TextEncoder().encode("beta"));
    const f3 = encodeFrame(5, 6, new TextEncoder().encode("gamma"));
    const stream = new Uint8Array(f1.length + f2.length + f3.length);
    stream.set(f1, 0);
    stream.set(f2, f1.length);
    stream.set(f3, f1.length + f2.length);
    const p = new FrameParser();
    const out = [];
    for (let i = 0; i < stream.length; i += 3) {
        out.push(...p.feed(stream.subarray(i, Math.min(i + 3, stream.length))));
    }
    assert.equal(out.length, 3);
    eq(out[0].payload, new TextEncoder().encode("alpha"));
    eq(out[1].payload, new TextEncoder().encode("beta"));
    eq(out[2].payload, new TextEncoder().encode("gamma"));
});

test("payload that contains AA 55 does not confuse the parser", () => {
    const nasty = new Uint8Array(100);
    for (let i = 0; i + 1 < nasty.length; i += 2) {
        nasty[i] = 0xaa;
        nasty[i + 1] = 0x55;
    }
    const f1 = encodeFrame(1, 1, nasty);
    const f2 = encodeFrame(2, 2, new TextEncoder().encode("next"));
    const stream = new Uint8Array(f1.length + f2.length);
    stream.set(f1, 0);
    stream.set(f2, f1.length);
    const p = new FrameParser();
    const frames = p.feed(stream);
    assert.equal(frames.length, 2);
    eq(frames[0].payload, nasty);
    eq(frames[1].payload, new TextEncoder().encode("next"));
});
