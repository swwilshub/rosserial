// Flasher: wraps esptool-js via CDN ESM. Loaded lazily so the page
// works even on browsers that lack WebSerial (manifest + console
// still render).

const ESPTOOL_CDN = "https://esm.sh/esptool-js@0.5.4";

let espToolMod = null;

async function loadEsptool() {
    if (espToolMod) return espToolMod;
    espToolMod = await import(ESPTOOL_CDN);
    return espToolMod;
}

async function sha256Hex(buf) {
    const h = await crypto.subtle.digest("SHA-256", buf);
    return Array.from(new Uint8Array(h))
        .map(b => b.toString(16).padStart(2, "0")).join("");
}

async function fetchBin(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(`fetch ${url}: HTTP ${r.status}`);
    return new Uint8Array(await r.arrayBuffer());
}

/**
 * Flash a manifest variant. Calls onLog(line) for each progress update.
 */
export async function flashVariant(variant, onLog) {
    const log = (line) => { onLog?.(line); console.log("[flash]", line); };
    log(`fetching ${variant.files.length} file(s)…`);

    const fileBytes = [];
    let concatLen = 0;
    for (const f of variant.files) {
        const data = await fetchBin(f.url);
        if (f.sha256) {
            const seen = await sha256Hex(data);
            if (seen !== f.sha256) {
                throw new Error(`${f.url}: sha256 mismatch (got ${seen}, want ${f.sha256})`);
            }
        }
        fileBytes.push({ data, offset: parseInt(f.offset, 16) });
        concatLen += data.length;
    }

    // Verify the aggregate firmware hash before flashing anything.
    const concat = new Uint8Array(concatLen);
    let off = 0;
    for (const { data } of fileBytes) {
        concat.set(data, off);
        off += data.length;
    }
    const aggregate = await sha256Hex(concat);
    if (aggregate !== variant.fwHash) {
        throw new Error(
            `firmware aggregate sha256 mismatch: got ${aggregate}, manifest says ${variant.fwHash}`
        );
    }
    log(`fwHash verified: ${aggregate}`);

    if (!("serial" in navigator)) {
        throw new Error("WebSerial not available in this browser");
    }
    const port = await navigator.serial.requestPort();
    log("port selected; loading esptool-js…");
    const { ESPLoader, Transport } = await loadEsptool();
    const transport = new Transport(port, true);
    const loader = new ESPLoader({
        transport,
        baudrate: 921600,
        romBaudrate: 115200,
        terminal: {
            clean: () => {},
            writeLine: (l) => log(l),
            write: (l) => log(l),
        },
    });

    log("connecting…");
    const chip = await loader.main();
    log(`detected: ${chip}`);

    log("writing flash…");
    const filesParam = fileBytes.map(({ data, offset }) => ({
        data: bytesToBinaryString(data),
        address: offset,
    }));
    await loader.writeFlash({
        fileArray: filesParam,
        flashSize: "keep",
        flashMode: "keep",
        flashFreq: "keep",
        eraseAll: false,
        compress: true,
        reportProgress: (i, written, total) => {
            log(`file ${i}: ${written}/${total} bytes`);
        },
    });
    log("done. resetting board…");
    await loader.after();
    await transport.disconnect();
    log("flash complete.");
}

// esptool-js expects each file's data as a binary string. Avoid
// String.fromCharCode(...arr) which can blow the stack on big arrays.
function bytesToBinaryString(arr) {
    let s = "";
    const CHUNK = 0x8000;
    for (let i = 0; i < arr.length; i += CHUNK) {
        s += String.fromCharCode.apply(null, arr.subarray(i, i + CHUNK));
    }
    return s;
}
