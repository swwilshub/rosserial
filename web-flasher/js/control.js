// Control-plane opcodes. Mirrors ros2-bridge/rosserial2/control.py
// for the opcodes the browser console needs to recognize.
//
// The console is decode-leaning: it parses HELLO/HELLO_ACK,
// ADVERTISE/ADVERTISE_ACK, PING/PONG, LOG, BYE. The encode side
// covers the bare minimum the console needs (HELLO_ACK, PONG) so it
// can play the bridge role for the local handshake demo.

export const Opcode = Object.freeze({
    HELLO: 0x01,
    HELLO_ACK: 0x02,
    ADVERTISE: 0x03,
    ADVERTISE_ACK: 0x04,
    PING: 0x05,
    PONG: 0x06,
    LOG: 0x07,
    BYE: 0xff,
});

export const Direction = Object.freeze({ PUBLISH: 0, SUBSCRIBE: 1 });

export const DEVICE_ID_LEN = 16;
export const FW_HASH_LEN = 20;

export class ControlError extends Error {}

function le16(buf, off) { return buf[off] | (buf[off + 1] << 8); }
function le32(buf, off) {
    return ((buf[off] |
        (buf[off + 1] << 8) |
        (buf[off + 2] << 16) |
        (buf[off + 3] << 24)) >>> 0);
}
function bytesToHex(buf) {
    return Array.from(buf, b => b.toString(16).padStart(2, "0")).join("");
}

/** Decode a control payload. Returns {opcode, ...fields} or throws. */
export function decodeControl(payload) {
    if (!(payload instanceof Uint8Array) || payload.length === 0) {
        throw new ControlError("empty control payload");
    }
    const op = payload[0];
    const body = payload.subarray(1);
    switch (op) {
        case Opcode.HELLO: {
            const expected = 1 + DEVICE_ID_LEN + FW_HASH_LEN + 2;
            if (body.length !== expected) {
                throw new ControlError(`HELLO body length: ${body.length}`);
            }
            return {
                opcode: Opcode.HELLO,
                protoVer: body[0],
                deviceId: body.subarray(1, 1 + DEVICE_ID_LEN),
                fwHash: body.subarray(1 + DEVICE_ID_LEN, 1 + DEVICE_ID_LEN + FW_HASH_LEN),
                maxPayload: le16(body, 1 + DEVICE_ID_LEN + FW_HASH_LEN),
            };
        }
        case Opcode.HELLO_ACK: {
            if (body.length !== 6) throw new ControlError("HELLO_ACK body length");
            return {
                opcode: Opcode.HELLO_ACK,
                protoVer: body[0],
                accepted: body[1],
                sessionId: le32(body, 2),
            };
        }
        case Opcode.ADVERTISE: {
            if (body.length < 3) throw new ControlError("ADVERTISE body too short");
            const topicId = body[0];
            const direction = body[1];
            if (direction > 1) throw new ControlError("ADVERTISE bad direction");
            const typeLen = body[2];
            if (body.length < 3 + typeLen + 1) {
                throw new ControlError("ADVERTISE truncated in type");
            }
            const typeStr = new TextDecoder().decode(body.subarray(3, 3 + typeLen));
            const nameLen = body[3 + typeLen];
            if (body.length !== 4 + typeLen + nameLen) {
                throw new ControlError("ADVERTISE size mismatch");
            }
            const name = new TextDecoder().decode(body.subarray(4 + typeLen));
            return { opcode: Opcode.ADVERTISE, topicId, direction, typeStr, name };
        }
        case Opcode.ADVERTISE_ACK: {
            if (body.length !== 2) throw new ControlError("ADVERTISE_ACK body length");
            return { opcode: Opcode.ADVERTISE_ACK, topicId: body[0], accepted: body[1] };
        }
        case Opcode.PING:
        case Opcode.PONG: {
            if (body.length !== 4) throw new ControlError("PING/PONG body length");
            return { opcode: op, nonce: le32(body, 0) };
        }
        case Opcode.LOG: {
            if (body.length < 1) throw new ControlError("LOG body too short");
            return {
                opcode: Opcode.LOG,
                level: body[0],
                message: new TextDecoder().decode(body.subarray(1)),
            };
        }
        case Opcode.BYE: {
            if (body.length !== 1) throw new ControlError("BYE body length");
            return { opcode: Opcode.BYE, reason: body[0] };
        }
        default:
            throw new ControlError(`unknown opcode: 0x${op.toString(16)}`);
    }
}

/** Encode a HELLO_ACK control payload. */
export function encodeHelloAck({ protoVer = 1, accepted = 1, sessionId = 1 } = {}) {
    const out = new Uint8Array(7);
    out[0] = Opcode.HELLO_ACK;
    out[1] = protoVer;
    out[2] = accepted;
    out[3] = sessionId & 0xff;
    out[4] = (sessionId >>> 8) & 0xff;
    out[5] = (sessionId >>> 16) & 0xff;
    out[6] = (sessionId >>> 24) & 0xff;
    return out;
}

/** Encode an ADVERTISE_ACK. */
export function encodeAdvertiseAck(topicId, accepted = 1) {
    return Uint8Array.of(Opcode.ADVERTISE_ACK, topicId & 0xff, accepted & 0xff);
}

/** Encode a PONG with the given nonce. */
export function encodePong(nonce) {
    const out = new Uint8Array(5);
    out[0] = Opcode.PONG;
    out[1] = nonce & 0xff;
    out[2] = (nonce >>> 8) & 0xff;
    out[3] = (nonce >>> 16) & 0xff;
    out[4] = (nonce >>> 24) & 0xff;
    return out;
}

export const helpers = { bytesToHex };
