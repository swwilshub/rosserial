// Tests for the BYO (bring-your-own-firmware) module.
//
// We test the pure pieces — presets, validateRows, parseHexOffset.
// The mountByo() UI is exercised manually in the browser.

import test from "node:test";
import assert from "node:assert/strict";

import { PRESETS, validateRows } from "../js/byo.js";
import { parseHexOffset } from "../js/flasher.js";

test("PRESETS expose Arduino layouts with correct offsets", () => {
    // ESP32 / S2 keep the legacy bootloader at 0x1000.
    assert.equal(PRESETS.arduino_esp32.rows[0].offset, "0x1000");
    assert.equal(PRESETS.arduino_esp32s2.rows[0].offset, "0x1000");
    // S3 / C3 / C6 boot from 0x0.
    for (const k of ["arduino_esp32s3", "arduino_esp32c3", "arduino_esp32c6"]) {
        assert.equal(PRESETS[k].rows[0].offset, "0x0");
    }
    // Every Arduino preset has bootloader, partitions, app.
    for (const k of ["arduino_esp32", "arduino_esp32s2", "arduino_esp32s3",
                     "arduino_esp32c3", "arduino_esp32c6"]) {
        const labels = PRESETS[k].rows.map(r => r.label);
        assert.deepEqual(labels, ["Bootloader", "Partitions", "Application"]);
        assert.equal(PRESETS[k].rows[1].offset, "0x8000");
        assert.equal(PRESETS[k].rows[2].offset, "0x10000");
    }
    assert.equal(PRESETS.merged_image.rows.length, 1);
    assert.equal(PRESETS.merged_image.rows[0].offset, "0x0");
});

test("validateRows rejects empty list", () => {
    const errs = validateRows([]);
    assert.ok(errs.some(e => /at least one/.test(e)));
});

test("validateRows rejects rows without a file", () => {
    const errs = validateRows([{ file: null, offset: "0x1000" }]);
    assert.ok(errs.some(e => /pick a file/.test(e)));
});

test("validateRows accepts valid rows", () => {
    const fakeFile = { name: "fw.bin", size: 100 };
    const errs = validateRows([
        { file: fakeFile, offset: "0x0" },
        { file: fakeFile, offset: "0x8000" },
    ]);
    assert.deepEqual(errs, []);
});

test("validateRows rejects duplicate offsets", () => {
    const fakeFile = { name: "x.bin", size: 1 };
    const errs = validateRows([
        { file: fakeFile, offset: "0x10000" },
        { file: fakeFile, offset: "0x10000" },
    ]);
    assert.ok(errs.some(e => /share offset/.test(e)));
});

test("parseHexOffset accepts 0x-prefixed and bare hex", () => {
    assert.equal(parseHexOffset("0x10000"), 0x10000);
    assert.equal(parseHexOffset("0X10000"), 0x10000);
    assert.equal(parseHexOffset("8000"), 0x8000);
    assert.equal(parseHexOffset("  0x0  "), 0);
});

test("parseHexOffset rejects bogus input", () => {
    assert.throws(() => parseHexOffset(""), /hex/);
    assert.throws(() => parseHexOffset("0xZZ"), /hex/);
    assert.throws(() => parseHexOffset("-1"), /hex/);
});
