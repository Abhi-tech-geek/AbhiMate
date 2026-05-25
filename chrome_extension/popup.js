// AbhiMate Recorder — popup script.
// Talks to the background SW via chrome.runtime.sendMessage. Owns no
// state of its own; every render pulls fresh state from the background.

const $ = (id) => document.getElementById(id);

const recordBtn   = $("recordBtn");
const clearBtn    = $("clearBtn");
const downloadBtn = $("downloadBtn");
const copyBtn     = $("copyBtn");
const featureInp  = $("featureInput");
const statusEl    = $("status");
const listEl      = $("actionList");
const exportRow   = $("exportRow");
const hintEl      = $("hint");


function send(msg) {
    return new Promise(resolve => {
        chrome.runtime.sendMessage(msg, (resp) => resolve(resp));
    });
}

function escapeText(s) {
    return String(s ?? "").replace(/[&<>]/g, ch => (
        {"&": "&amp;", "<": "&lt;", ">": "&gt;"}[ch]
    ));
}

function renderActions(actions) {
    listEl.textContent = "";
    if (!actions || !actions.length) return;
    actions.forEach((a) => {
        const li = document.createElement("li");
        const op = document.createElement("span");
        op.className = "op";
        op.textContent = a.op;
        li.appendChild(op);

        const val = document.createElement("span");
        val.className = "val";
        if (a.op === "goto") {
            val.textContent = a.url || "";
        } else if (a.locator) {
            const v = (a.value != null) ? ` = ${JSON.stringify(a.value)}` : "";
            val.textContent = `${a.locator.by}:${a.locator.value}${v}`;
        } else {
            val.textContent = a.value != null ? JSON.stringify(a.value) : "";
        }
        li.appendChild(val);
        listEl.appendChild(li);
    });
}

function setRecordingUI(recording) {
    document.body.classList.toggle("is-recording", !!recording);
    if (recording) {
        recordBtn.textContent = "■ Stop recording";
        statusEl.textContent = "recording";
        statusEl.classList.add("is-recording");
        featureInp.disabled = true;
    } else {
        recordBtn.textContent = "● Start recording";
        statusEl.textContent = "idle";
        statusEl.classList.remove("is-recording");
        featureInp.disabled = false;
    }
}

async function refresh() {
    const {state, actions} = await send({type: "get-status"});
    setRecordingUI(state?.recording);
    if (state?.feature && !featureInp.value) featureInp.value = state.feature;
    renderActions(actions);
    exportRow.hidden = !(actions && actions.length && !state?.recording);
}


// ---------------------------------------------------------------------
// Button handlers
// ---------------------------------------------------------------------

recordBtn.addEventListener("click", async () => {
    const {state} = await send({type: "get-status"});
    if (state?.recording) {
        const stopped = await send({type: "stop-recording"});
        // Best-effort: ask the content script in the active tab to detach.
        try {
            const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
            if (tab?.id) chrome.tabs.sendMessage(tab.id, {type: "stop-content-recording"});
        } catch (_) {}
        await refresh();
    } else {
        await send({
            type: "start-recording",
            feature: featureInp.value.trim(),
        });
        await refresh();
    }
});

clearBtn.addEventListener("click", async () => {
    if (!confirm("Discard the current recording?")) return;
    await send({type: "clear-recording"});
    featureInp.value = "";
    await refresh();
});


// ---------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------

async function buildExportPayload() {
    const {state, actions} = await send({type: "get-status"});
    const firstGoto = (actions || []).find(a => a.op === "goto");
    return {
        version: 1,
        feature: state?.feature || featureInp.value.trim() || "Recorded session",
        url: firstGoto?.url || null,
        recorded_at: (state?.startedAt || Date.now()) / 1000,
        actions: actions || [],
    };
}

downloadBtn.addEventListener("click", async () => {
    const payload = await buildExportPayload();
    const blob = new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"});
    const url = URL.createObjectURL(blob);
    const fname = (payload.feature || "recording")
        .replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 60) + ".abhimate.json";
    const a = document.createElement("a");
    a.href = url; a.download = fname;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
});

copyBtn.addEventListener("click", async () => {
    const payload = await buildExportPayload();
    try {
        await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
        copyBtn.textContent = "Copied ✓";
        setTimeout(() => { copyBtn.textContent = "Copy to clipboard"; }, 1200);
    } catch (e) {
        copyBtn.textContent = "Failed";
    }
});


// Refresh on open + on storage changes (so the action list ticks up live).
refresh();
chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    refresh();
});
