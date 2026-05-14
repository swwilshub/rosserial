// WebSerial console.
//
// Plays the bridge role from inside the browser: replies to HELLO,
// accepts ADVERTISE (any type), replies to PING, prints decoded
// traffic. The user sees their device behaving correctly without
// needing ROS2.
//
// Single client at a time. Disconnect cleanly via stop().

import { FrameParser, encodeFrame, CONTROL_MSG_ID } from "./codec.js";
import {
    Opcode,
    Direction,
    decodeControl,
    encodeHelloAck,
    encodeAdvertiseAck,
    encodePong,
} from "./control.js";

export class ConsoleSession {
    /**
     * @param {object} hooks
     * @param {(line:string)=>void} hooks.onLog
     * @param {(topics: Array)=>void} hooks.onTopics
     * @param {(state:string)=>void} hooks.onState
     */
    constructor(hooks) {
        this.hooks = hooks;
        this.port = null;
        this.reader = null;
        this.writer = null;
        this.parser = new FrameParser();
        this.txSeq = 0;
        this.topics = new Map();   // topic_id -> {name, type, direction}
        this.sessionId = 0;
        this.stopped = false;
    }

    log(line) { this.hooks.onLog?.(line); }
    state(s)  { this.hooks.onState?.(s); }
    publishTopicList() {
        const arr = Array.from(this.topics, ([id, t]) => ({ id, ...t }));
        this.hooks.onTopics?.(arr);
    }

    async start(port, { baudRate = 921600 } = {}) {
        this.port = port;
        await port.open({ baudRate });
        this.reader = port.readable.getReader();
        this.writer = port.writable.getWriter();
        this.state("connected");
        this.log(`opened serial @ ${baudRate} baud`);
        this._loop().catch(err => {
            this.log(`read loop error: ${err}`);
            this.state("error");
        });
    }

    async stop() {
        this.stopped = true;
        try { await this.reader?.cancel(); } catch {}
        try { this.writer?.releaseLock(); } catch {}
        try { await this.port?.close(); } catch {}
        this.state("disconnected");
    }

    async _send(msgId, payload) {
        const frame = encodeFrame(this.txSeq, msgId, payload);
        this.txSeq = (this.txSeq + 1) & 0xff;
        await this.writer.write(frame);
    }

    async _loop() {
        while (!this.stopped) {
            const { value, done } = await this.reader.read();
            if (done) break;
            if (!value) continue;
            const frames = this.parser.feed(new Uint8Array(value));
            for (const f of frames) await this._handleFrame(f);
        }
    }

    async _handleFrame(frame) {
        if (frame.msgId === CONTROL_MSG_ID) {
            await this._handleControl(frame);
        } else {
            this._handleData(frame);
        }
    }

    async _handleControl(frame) {
        let msg;
        try { msg = decodeControl(frame.payload); }
        catch (e) {
            this.log(`bad control payload: ${e.message}`);
            return;
        }
        switch (msg.opcode) {
            case Opcode.HELLO: {
                this.sessionId = (this.sessionId + 1) >>> 0;
                this.topics.clear();
                this.publishTopicList();
                this.log(`<- HELLO proto=${msg.protoVer} maxPayload=${msg.maxPayload}`);
                await this._send(
                    CONTROL_MSG_ID,
                    encodeHelloAck({
                        protoVer: 1,
                        accepted: 1,
                        sessionId: this.sessionId,
                    })
                );
                this.log(`-> HELLO_ACK sessionId=${this.sessionId}`);
                break;
            }
            case Opcode.ADVERTISE: {
                const dirStr = msg.direction === Direction.PUBLISH ? "pub" : "sub";
                this.topics.set(msg.topicId, {
                    name: msg.name, type: msg.typeStr, direction: dirStr,
                });
                this.publishTopicList();
                this.log(
                    `<- ADVERTISE id=${msg.topicId} ${dirStr} ${msg.typeStr} ${msg.name}`
                );
                await this._send(
                    CONTROL_MSG_ID,
                    encodeAdvertiseAck(msg.topicId, 1),
                );
                this.log(`-> ADVERTISE_ACK id=${msg.topicId} accepted=1`);
                break;
            }
            case Opcode.PING: {
                await this._send(CONTROL_MSG_ID, encodePong(msg.nonce));
                this.log(`<- PING nonce=0x${msg.nonce.toString(16)} -> PONG`);
                break;
            }
            case Opcode.LOG: {
                this.log(`device LOG[${msg.level}]: ${msg.message}`);
                break;
            }
            case Opcode.BYE: {
                this.log(`<- BYE reason=${msg.reason}`);
                break;
            }
            default:
                this.log(`<- opcode 0x${msg.opcode.toString(16)} (unhandled)`);
        }
    }

    _handleData(frame) {
        const entry = this.topics.get(frame.msgId);
        if (!entry) {
            this.log(`data on unknown topic_id=${frame.msgId} (len ${frame.payload.length})`);
            return;
        }
        const preview = previewBytes(frame.payload);
        this.log(`<- ${entry.name} (${entry.type}) [${frame.payload.length}B] ${preview}`);
    }
}

function previewBytes(arr) {
    const hex = Array.from(arr.subarray(0, 16),
        b => b.toString(16).padStart(2, "0")).join(" ");
    return arr.length > 16 ? hex + " …" : hex;
}
