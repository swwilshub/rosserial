// Bring-your-own-firmware support.
//
// A user who built firmware in Arduino IDE (or anywhere else) can
// supply their own .bin files and flash them via the same WebSerial
// pipeline used for the manifest. We give them a few canonical
// presets so they don't have to remember which offset goes where.
//
// Arduino IDE 2.x's "Sketch → Export Compiled Binary" produces three
// files next to the .ino: <sketch>.ino.bootloader.bin,
// <sketch>.ino.partitions.bin, and <sketch>.ino.bin. The bootloader
// offset varies by chip family.

/**
 * Canonical row presets. Each row carries a label and the default
 * offset for that file slot. Users can edit the offset before
 * flashing if they have an unusual layout.
 */
export const PRESETS = Object.freeze({
    arduino_esp32: {
        label: "Arduino ESP32 (3 files)",
        rows: [
            { label: "Bootloader",  offset: "0x1000" },
            { label: "Partitions",  offset: "0x8000" },
            { label: "Application", offset: "0x10000" },
        ],
    },
    arduino_esp32s2: {
        label: "Arduino ESP32-S2 (3 files)",
        rows: [
            { label: "Bootloader",  offset: "0x1000" },
            { label: "Partitions",  offset: "0x8000" },
            { label: "Application", offset: "0x10000" },
        ],
    },
    arduino_esp32s3: {
        label: "Arduino ESP32-S3 (3 files)",
        rows: [
            { label: "Bootloader",  offset: "0x0" },
            { label: "Partitions",  offset: "0x8000" },
            { label: "Application", offset: "0x10000" },
        ],
    },
    arduino_esp32c3: {
        label: "Arduino ESP32-C3 (3 files)",
        rows: [
            { label: "Bootloader",  offset: "0x0" },
            { label: "Partitions",  offset: "0x8000" },
            { label: "Application", offset: "0x10000" },
        ],
    },
    arduino_esp32c6: {
        label: "Arduino ESP32-C6 (3 files)",
        rows: [
            { label: "Bootloader",  offset: "0x0" },
            { label: "Partitions",  offset: "0x8000" },
            { label: "Application", offset: "0x10000" },
        ],
    },
    merged_image: {
        label: "Single merged image",
        rows: [
            { label: "Merged image", offset: "0x0" },
        ],
    },
    custom: {
        label: "Custom (one row, add more as needed)",
        rows: [
            { label: "File 1", offset: "0x10000" },
        ],
    },
});

/** Validate a parsed BYO row set before flashing. Returns errors[]. */
export function validateRows(entries) {
    const errors = [];
    if (entries.length === 0) errors.push("add at least one file");
    const seen = new Map();  // offset -> first index
    for (const [i, e] of entries.entries()) {
        if (!e.file) {
            errors.push(`row ${i + 1}: pick a file`);
            continue;
        }
        let off;
        try { off = parseInt(e.offset, 16); }
        catch { errors.push(`row ${i + 1}: offset not hex`); continue; }
        if (!Number.isFinite(off) || off < 0) {
            errors.push(`row ${i + 1}: offset must be a non-negative hex number`);
            continue;
        }
        if (seen.has(off)) {
            errors.push(
                `rows ${seen.get(off) + 1} and ${i + 1} share offset 0x${off.toString(16)}`,
            );
        } else {
            seen.set(off, i);
        }
    }
    return errors;
}

/** Mount the BYO UI inside a container element. */
export function mountByo({ container, onFlash }) {
    container.innerHTML = `
        <div class="byo-controls">
            <label>
                Layout preset:
                <select class="byo-preset"></select>
            </label>
            <button type="button" class="byo-add secondary">+ Add row</button>
        </div>
        <table class="byo-rows">
            <thead><tr>
                <th>Label</th><th>File</th><th>Offset (hex)</th><th></th>
            </tr></thead>
            <tbody></tbody>
        </table>
        <div class="byo-error error"></div>
        <button type="button" class="byo-flash">Flash these files</button>
        <pre class="log byo-log"></pre>
    `;

    const select = container.querySelector(".byo-preset");
    const tbody  = container.querySelector(".byo-rows tbody");
    const errEl  = container.querySelector(".byo-error");
    const logEl  = container.querySelector(".byo-log");
    const flashBtn = container.querySelector(".byo-flash");
    const addBtn = container.querySelector(".byo-add");

    for (const [key, p] of Object.entries(PRESETS)) {
        const opt = document.createElement("option");
        opt.value = key;
        opt.textContent = p.label;
        select.appendChild(opt);
    }
    select.value = "arduino_esp32s3";

    function renderRows(rows) {
        tbody.innerHTML = "";
        for (const r of rows) addRow(r.label, r.offset);
    }

    function addRow(label = "", offset = "0x10000") {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td><input class="row-label" type="text" value="${escapeAttr(label)}" /></td>
            <td><input class="row-file" type="file" accept=".bin,application/octet-stream" /></td>
            <td><input class="row-offset" type="text" value="${escapeAttr(offset)}" size="10" /></td>
            <td><button type="button" class="row-remove secondary">×</button></td>
        `;
        tr.querySelector(".row-remove").addEventListener("click", () => tr.remove());
        tbody.appendChild(tr);
    }

    function readEntries() {
        return Array.from(tbody.querySelectorAll("tr")).map((tr) => ({
            label: tr.querySelector(".row-label").value,
            file: tr.querySelector(".row-file").files[0] ?? null,
            offset: tr.querySelector(".row-offset").value,
        }));
    }

    select.addEventListener("change", () => {
        renderRows(PRESETS[select.value].rows);
        errEl.textContent = "";
    });
    addBtn.addEventListener("click", () => addRow("File", "0x"));
    flashBtn.addEventListener("click", async () => {
        errEl.textContent = "";
        logEl.textContent = "";
        const entries = readEntries();
        const errs = validateRows(entries);
        if (errs.length > 0) {
            errEl.textContent = errs.join(" · ");
            return;
        }
        flashBtn.disabled = true;
        try {
            await onFlash(entries, (line) => {
                logEl.textContent += line + "\n";
                logEl.scrollTop = logEl.scrollHeight;
            });
        } catch (e) {
            logEl.textContent += `\nERROR: ${e.message}\n`;
        } finally {
            flashBtn.disabled = false;
        }
    });

    // Initial render.
    renderRows(PRESETS[select.value].rows);
}

function escapeAttr(s) {
    return String(s).replaceAll("&", "&amp;").replaceAll('"', "&quot;");
}
