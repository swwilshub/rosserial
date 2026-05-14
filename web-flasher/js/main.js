// UI wiring. Imports the codec/control modules + manifest + flasher
// + console. Stays small: each module owns its own logic.

import { loadManifest } from "./manifest.js";
import { ConsoleSession } from "./console.js";

const $ = (sel) => document.querySelector(sel);

function setCap(name, ok, hint) {
    const el = document.querySelector(`[data-cap="${name}"]`);
    if (!el) return;
    el.textContent = ok ? "yes" : (hint ?? "no");
    el.classList.toggle("ok", !!ok);
    el.classList.toggle("error", !ok);
}

function checkCapabilities() {
    setCap("webserial", "serial" in navigator);
    setCap("secure", window.isSecureContext);
}

let activeVariant = null;
let activeConsole = null;

async function renderManifest() {
    try {
        const m = await loadManifest("manifest.json");
        const meta = $("#manifest-meta");
        const bits = [
            m.releaseTag ? `release: ${m.releaseTag}` : null,
            m.commitSha ? `commit: ${m.commitSha.substring(0, 8)}` : null,
            m.generatedAt ? `generated: ${m.generatedAt}` : null,
            m.ciRunUrl ? `<a href="${m.ciRunUrl}">CI run</a>` : null,
        ].filter(Boolean);
        meta.innerHTML = bits.length
            ? bits.join(" · ")
            : "no release tag yet — flash via <code>idf.py</code> and use the Console below";

        const list = $("#variants");
        list.innerHTML = "";
        if (m.variants.length === 0) {
            const li = document.createElement("li");
            li.innerHTML =
                `<div><div class="label">No variants in this manifest</div>` +
                `<div class="sub">CI populates this on each tagged release.</div></div>`;
            list.appendChild(li);
            return;
        }
        for (const v of m.variants) {
            const li = document.createElement("li");
            const label = v.label ?? `${v.board} · ${v.example} · ${v.transport}`;
            li.innerHTML = `
                <div>
                    <div class="label">${escapeHtml(label)}</div>
                    <div class="sub">
                        board=<code>${escapeHtml(v.board)}</code>
                        transport=<code>${escapeHtml(v.transport)}</code>
                        example=<code>${escapeHtml(v.example)}</code>
                    </div>
                    <div class="sub">fwHash <code>${v.fwHash.substring(0, 12)}…</code></div>
                </div>
                <button class="select">Select</button>
            `;
            li.querySelector("button").addEventListener("click", () => selectVariant(v, m));
            list.appendChild(li);
        }
    } catch (e) {
        $("#manifest-meta").innerHTML =
            `<span class="error">failed to load manifest: ${escapeHtml(e.message)}</span>`;
    }
}

function selectVariant(v, manifest) {
    activeVariant = v;
    $("#flasher").classList.remove("hidden");
    $("#flash-selected").textContent =
        v.label ?? `${v.board}/${v.example}/${v.transport}`;
    $("#flash-hash").textContent = v.fwHash;
    $("#flash-commit").textContent = manifest.commitSha ?? "(none)";
    const ciSpan = $("#flash-ci-link");
    ciSpan.innerHTML = manifest.ciRunUrl
        ? ` · <a href="${manifest.ciRunUrl}">CI run</a>`
        : "";
    $("#flash-log").textContent = "";
}

async function onFlashConfirm() {
    if (!activeVariant) return;
    const btn = $("#flash-button");
    btn.disabled = true;
    const log = $("#flash-log");
    try {
        // Dynamic import so the (heavy) esptool-js fetch happens only
        // when the user actually clicks flash.
        const { flashVariant } = await import("./flasher.js");
        await flashVariant(activeVariant, (line) => {
            log.textContent += line + "\n";
            log.scrollTop = log.scrollHeight;
        });
    } catch (e) {
        log.textContent += `\nERROR: ${e.message}\n`;
    } finally {
        btn.disabled = false;
    }
}

async function onConsoleConnect() {
    if (!("serial" in navigator)) {
        consoleLog("WebSerial not available in this browser.");
        return;
    }
    let port;
    try {
        port = await navigator.serial.requestPort();
    } catch (e) {
        consoleLog(`cancelled or denied: ${e.message}`);
        return;
    }
    activeConsole = new ConsoleSession({
        onLog: consoleLog,
        onTopics: renderTopics,
        onState: setConsoleState,
    });
    $("#console-connect").disabled = true;
    $("#console-disconnect").disabled = false;
    try {
        await activeConsole.start(port);
    } catch (e) {
        consoleLog(`open failed: ${e.message}`);
        $("#console-connect").disabled = false;
        $("#console-disconnect").disabled = true;
    }
}

async function onConsoleDisconnect() {
    if (!activeConsole) return;
    await activeConsole.stop();
    activeConsole = null;
    $("#console-connect").disabled = false;
    $("#console-disconnect").disabled = true;
}

function consoleLog(line) {
    const el = $("#console-log");
    el.textContent += line + "\n";
    el.scrollTop = el.scrollHeight;
}

function setConsoleState(s) {
    const el = $("#console-status");
    el.textContent = s;
    el.classList.toggle("connected", s === "connected");
    el.classList.toggle("error", s === "error");
}

function renderTopics(topics) {
    const ul = $("#console-topics");
    ul.innerHTML = "";
    if (topics.length === 0) {
        const li = document.createElement("li");
        li.textContent = "(no topics yet)";
        ul.appendChild(li);
        return;
    }
    for (const t of topics) {
        const li = document.createElement("li");
        const cls = t.direction === "pub" ? "pub" : "sub";
        li.innerHTML =
            `<span class="id">${t.id}</span> ` +
            `<span class="${cls}">${escapeHtml(t.direction)}</span> ` +
            `${escapeHtml(t.type)} <strong>${escapeHtml(t.name)}</strong>`;
        ul.appendChild(li);
    }
}

function escapeHtml(s) {
    return String(s)
        .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

// --- boot --------------------------------------------------------

window.addEventListener("DOMContentLoaded", () => {
    checkCapabilities();
    renderManifest();
    $("#flash-button").addEventListener("click", onFlashConfirm);
    $("#flash-cancel").addEventListener("click", () => {
        activeVariant = null;
        $("#flasher").classList.add("hidden");
    });
    $("#console-connect").addEventListener("click", onConsoleConnect);
    $("#console-disconnect").addEventListener("click", onConsoleDisconnect);
});
