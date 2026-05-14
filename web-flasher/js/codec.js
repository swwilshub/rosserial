// rosserial2 wire codec — ES module, browser- and Node-compatible.
//
// Mirrors ros2-bridge/rosserial2/codec.py exactly. Same constants,
// same frame layout, same one-byte-rewind streaming parser. The
// cross-language corpus checked into
// ros2-bridge/tests/corpus/ keeps the three implementations in sync.

export const SYNC = Uint8Array.of(0xaa, 0x55);
export const HEADER_SIZE = 6;       // SYNC(2)+LEN(2)+SEQ(1)+MSG_ID(1)
export const CRC_SIZE = 4;
export const OVERHEAD = HEADER_SIZE + CRC_SIZE; // 10
export const MAX_PAYLOAD = 512;
export const CONTROL_MSG_ID = 0;
export const PROTOCOL_VERSION = 1;

export class FrameError extends Error {}

/** IEEE 802.3 CRC32 (poly 0xEDB88320), bitwise. Returns u32. */
export function crc32(bytes) {
    let crc = 0xffffffff >>> 0;
    for (let i = 0; i < bytes.length; i++) {
        crc = (crc ^ bytes[i]) >>> 0;
        for (let b = 0; b < 8; b++) {
            const mask = -(crc & 1) >>> 0;
            crc = ((crc >>> 1) ^ (0xedb88320 & mask)) >>> 0;
        }
    }
    return (~crc) >>> 0;
}

function checkRange(name, value, lo, hi) {
    if (!Number.isInteger(value) || value < lo || value > hi) {
        throw new FrameError(`${name} out of range: ${value}`);
    }
}

/**
 * Encode a frame.
 * @param {number} seq     0..255
 * @param {number} msgId   0..255
 * @param {Uint8Array} payload  length <= MAX_PAYLOAD
 * @returns {Uint8Array}
 */
export function encodeFrame(seq, msgId, payload) {
    checkRange("seq", seq, 0, 0xff);
    checkRange("msg_id", msgId, 0, 0xff);
    if (!(payload instanceof Uint8Array)) {
        throw new FrameError("payload must be a Uint8Array");
    }
    if (payload.length > MAX_PAYLOAD) {
        throw new FrameError(`payload too large: ${payload.length} > ${MAX_PAYLOAD}`);
    }
    const length = payload.length;
    const total = OVERHEAD + length;
    const out = new Uint8Array(total);
    out[0] = 0xaa;
    out[1] = 0x55;
    out[2] = length & 0xff;
    out[3] = (length >>> 8) & 0xff;
    out[4] = seq;
    out[5] = msgId;
    out.set(payload, HEADER_SIZE);
    const crc = crc32(out.subarray(2, HEADER_SIZE + length));
    const crcOffset = HEADER_SIZE + length;
    out[crcOffset + 0] = crc & 0xff;
    out[crcOffset + 1] = (crc >>> 8) & 0xff;
    out[crcOffset + 2] = (crc >>> 16) & 0xff;
    out[crcOffset + 3] = (crc >>> 24) & 0xff;
    return out;
}

/**
 * Decode exactly one frame.
 * @param {Uint8Array} buf
 * @returns {{seq:number, msgId:number, payload:Uint8Array}}
 */
export function decodeFrame(buf) {
    if (!(buf instanceof Uint8Array)) {
        throw new FrameError("buf must be a Uint8Array");
    }
    if (buf.length < OVERHEAD) {
        throw new FrameError(`buffer too short: ${buf.length} < ${OVERHEAD}`);
    }
    if (buf[0] !== 0xaa || buf[1] !== 0x55) {
        throw new FrameError("bad sync");
    }
    const length = buf[2] | (buf[3] << 8);
    if (length > MAX_PAYLOAD) {
        throw new FrameError(`length out of range: ${length}`);
    }
    const total = OVERHEAD + length;
    if (buf.length !== total) {
        throw new FrameError(`size mismatch: got ${buf.length}, expected ${total}`);
    }
    const seq = buf[4];
    const msgId = buf[5];
    const payload = buf.slice(HEADER_SIZE, HEADER_SIZE + length);
    const crcOffset = HEADER_SIZE + length;
    const crcActual =
        (buf[crcOffset] |
            (buf[crcOffset + 1] << 8) |
            (buf[crcOffset + 2] << 16) |
            (buf[crcOffset + 3] << 24)) >>> 0;
    const crcExpected = crc32(buf.subarray(2, crcOffset));
    if (crcActual !== crcExpected) {
        throw new FrameError(
            `crc mismatch: got 0x${crcActual.toString(16)}, expected 0x${crcExpected.toString(16)}`
        );
    }
    return { seq, msgId, payload };
}

/**
 * Streaming parser. ``feed(bytes)`` returns any complete frames
 * produced. Mirrors the Python parser's one-byte-rewind rule.
 */
export class FrameParser {
    constructor() {
        this._buf = new Uint8Array(0);
        this.errors = 0;
        this.bytesSeen = 0;
    }

    reset() {
        this._buf = new Uint8Array(0);
    }

    feed(data) {
        if (!(data instanceof Uint8Array)) {
            throw new FrameError("feed() requires Uint8Array");
        }
        this.bytesSeen += data.length;
        // Concatenate.
        const merged = new Uint8Array(this._buf.length + data.length);
        merged.set(this._buf, 0);
        merged.set(data, this._buf.length);
        this._buf = merged;

        const out = [];
        while (true) {
            const { frame, advance } = this._tryOne();
            if (advance === 0) break;
            this._buf = this._buf.subarray(advance);
            if (frame !== null) out.push(frame);
        }
        return out;
    }

    _tryOne() {
        const buf = this._buf;
        if (buf.length === 0) return { frame: null, advance: 0 };
        let start = 0;
        while (start < buf.length && buf[start] !== 0xaa) start++;
        if (start > 0) return { frame: null, advance: start };
        if (buf.length < 2) return { frame: null, advance: 0 };
        if (buf[1] !== 0x55) return { frame: null, advance: 1 };
        if (buf.length < HEADER_SIZE) return { frame: null, advance: 0 };
        const length = buf[2] | (buf[3] << 8);
        if (length > MAX_PAYLOAD) {
            this.errors++;
            return { frame: null, advance: 1 };
        }
        const total = OVERHEAD + length;
        if (buf.length < total) return { frame: null, advance: 0 };
        const crcOffset = HEADER_SIZE + length;
        const crcActual =
            (buf[crcOffset] |
                (buf[crcOffset + 1] << 8) |
                (buf[crcOffset + 2] << 16) |
                (buf[crcOffset + 3] << 24)) >>> 0;
        const crcExpected = crc32(buf.subarray(2, crcOffset));
        if (crcActual !== crcExpected) {
            this.errors++;
            return { frame: null, advance: 1 };
        }
        const frame = {
            seq: buf[4],
            msgId: buf[5],
            payload: buf.slice(HEADER_SIZE, HEADER_SIZE + length),
        };
        return { frame, advance: total };
    }
}
