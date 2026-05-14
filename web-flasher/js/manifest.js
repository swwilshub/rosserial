// Manifest loader. The manifest is a small JSON file produced by CI
// and pinned to a release tag. See manifest.schema.json.

export async function loadManifest(url = "manifest.json") {
    const resp = await fetch(url, { cache: "no-store" });
    if (!resp.ok) {
        throw new Error(`manifest fetch failed: HTTP ${resp.status}`);
    }
    const m = await resp.json();
    return validate(m);
}

function validate(m) {
    if (typeof m !== "object" || m === null) {
        throw new Error("manifest must be an object");
    }
    if (typeof m.wireVersion !== "number") {
        throw new Error("manifest missing wireVersion");
    }
    if (!Array.isArray(m.variants)) {
        throw new Error("manifest missing variants array");
    }
    for (const v of m.variants) {
        for (const k of ["board", "transport", "example", "files", "fwHash"]) {
            if (!(k in v)) throw new Error(`variant missing key: ${k}`);
        }
        if (!Array.isArray(v.files) || v.files.length === 0) {
            throw new Error("variant.files must be a non-empty array");
        }
    }
    return m;
}
