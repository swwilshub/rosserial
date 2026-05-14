// Control-plane opcode tests. The corpus tests cover frame parity;
// these check that the JS decoder reads each opcode shape correctly
// from frames produced by the Python encoder.

import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { decodeFrame } from "../js/codec.js";
import { Opcode, Direction, decodeControl, encodeHelloAck, encodePong } from "../js/control.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const GOLDEN = path.resolve(__dirname, "../../ros2-bridge/tests/golden");

test("golden HELLO decodes", async () => {
    const buf = new Uint8Array(await readFile(path.join(GOLDEN, "hello.bin")));
    const f = decodeFrame(buf);
    const c = decodeControl(f.payload);
    assert.equal(c.opcode, Opcode.HELLO);
    assert.equal(c.protoVer, 1);
    assert.equal(c.maxPayload, 512);
    assert.equal(c.deviceId.length, 16);
    assert.equal(c.deviceId[0], 0xaa);
    assert.equal(c.fwHash.length, 20);
    assert.equal(c.fwHash[0], 0xbb);
});

test("golden ADVERTISE decodes", async () => {
    const buf = new Uint8Array(await readFile(path.join(GOLDEN, "advertise.bin")));
    const f = decodeFrame(buf);
    const c = decodeControl(f.payload);
    assert.equal(c.opcode, Opcode.ADVERTISE);
    assert.equal(c.topicId, 7);
    assert.equal(c.direction, Direction.PUBLISH);
    assert.equal(c.typeStr, "std_msgs/msg/String");
    assert.equal(c.name, "chatter");
});

test("golden PING decodes", async () => {
    const buf = new Uint8Array(await readFile(path.join(GOLDEN, "ping.bin")));
    const f = decodeFrame(buf);
    const c = decodeControl(f.payload);
    assert.equal(c.opcode, Opcode.PING);
    assert.equal(c.nonce, 0xdeadbeef);
});

test("encodeHelloAck shape", () => {
    const out = encodeHelloAck({ protoVer: 1, accepted: 1, sessionId: 0x12345678 });
    assert.equal(out.length, 7);
    assert.equal(out[0], Opcode.HELLO_ACK);
    assert.equal(out[1], 1);
    assert.equal(out[2], 1);
    assert.equal(out[3], 0x78);
    assert.equal(out[4], 0x56);
    assert.equal(out[5], 0x34);
    assert.equal(out[6], 0x12);
});

test("encodePong shape", () => {
    const out = encodePong(0xcafebabe);
    assert.equal(out.length, 5);
    assert.equal(out[0], Opcode.PONG);
    assert.equal(out[1], 0xbe);
    assert.equal(out[2], 0xba);
    assert.equal(out[3], 0xfe);
    assert.equal(out[4], 0xca);
});
