// Tests for the manifest loader. Spins up a tiny localhost HTTP
// server so the loader's fetch() works under Node --test.

import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";

import { loadManifest } from "../js/manifest.js";

function serveOnce(payload, contentType = "application/json") {
    return new Promise((resolve) => {
        const server = http.createServer((req, res) => {
            res.writeHead(200, { "content-type": contentType });
            res.end(payload);
        });
        server.listen(0, "127.0.0.1", () => {
            const port = server.address().port;
            resolve({
                url: `http://127.0.0.1:${port}/manifest.json`,
                close: () => new Promise(r => server.close(r)),
            });
        });
    });
}

test("loadManifest accepts preview variants (empty files list)", async () => {
    const { url, close } = await serveOnce(JSON.stringify({
        wireVersion: 1,
        variants: [{
            board: "esp32s3",
            example: "hello_publisher",
            transport: "serial",
            preview: true,
            fwHash: "00".repeat(32),
            files: [],
        }],
    }));
    try {
        const m = await loadManifest(url);
        assert.equal(m.variants.length, 1);
        assert.equal(m.variants[0].preview, true);
    } finally {
        await close();
    }
});

test("loadManifest accepts a real variant with one file", async () => {
    const { url, close } = await serveOnce(JSON.stringify({
        wireVersion: 1,
        variants: [{
            board: "esp32s3",
            example: "hello_publisher",
            transport: "serial",
            fwHash: "ab".repeat(32),
            files: [{ url: "fw.bin", offset: "0x10000" }],
        }],
    }));
    try {
        const m = await loadManifest(url);
        assert.equal(m.variants[0].files.length, 1);
    } finally {
        await close();
    }
});

test("loadManifest rejects empty files when not preview", async () => {
    const { url, close } = await serveOnce(JSON.stringify({
        wireVersion: 1,
        variants: [{
            board: "esp32s3",
            example: "x",
            transport: "serial",
            fwHash: "00".repeat(32),
            files: [],
        }],
    }));
    try {
        await assert.rejects(loadManifest(url), /non-empty/);
    } finally {
        await close();
    }
});

test("loadManifest rejects missing wireVersion", async () => {
    const { url, close } = await serveOnce(JSON.stringify({ variants: [] }));
    try {
        await assert.rejects(loadManifest(url), /wireVersion/);
    } finally {
        await close();
    }
});

test("loadManifest accepts the checked-in manifest.json", async () => {
    const { readFile } = await import("node:fs/promises");
    const { fileURLToPath } = await import("node:url");
    const path = await import("node:path");
    const here = path.dirname(fileURLToPath(import.meta.url));
    const data = await readFile(path.resolve(here, "../manifest.json"));
    const { url, close } = await serveOnce(data);
    try {
        const m = await loadManifest(url);
        // Currently three preview entries.
        assert.ok(m.variants.length >= 1);
        for (const v of m.variants) {
            assert.ok("board" in v && "transport" in v && "example" in v);
        }
    } finally {
        await close();
    }
});
