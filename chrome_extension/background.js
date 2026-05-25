// AbhiMate Recorder — background service worker.
//
// Responsibilities:
//   * Hold the canonical "is-recording" flag + the in-progress action list.
//     (Service workers go to sleep, so we mirror everything to chrome.storage
//     so the popup and content script see the same view after a restart.)
//   * Inject / un-inject the content script when the user toggles record.
//   * Listen for tab navigations and append a `goto` action — the content
//     script can't see top-frame nav events itself.
//   * Forward `recorded-action` messages from the content script to storage.
//
// We deliberately do NOT post to AbhiMate from here. The popup writes a
// JSON file via the downloads API and the user uploads it from the
// AbhiMate UI — no API token to manage, no CORS, no auth state in the
// extension. Simpler and easier to test.

const STORAGE_KEYS = {
    state: "abhimate_recorder_state",
    actions: "abhimate_recorder_actions",
};

const DEFAULT_STATE = {
    recording: false,
    tabId: null,           // which tab we're recording — others are ignored
    startedAt: null,       // epoch ms
    feature: "",
    lastUrl: null,         // dedupes goto events when SPA navigations fire twice
};


// ---------------------------------------------------------------------
// Tiny chrome.storage helpers (promise-based)
// ---------------------------------------------------------------------

function getState() {
    return new Promise(resolve => {
        chrome.storage.local.get([STORAGE_KEYS.state], data => {
            resolve(data[STORAGE_KEYS.state] || {...DEFAULT_STATE});
        });
    });
}

function setState(patch) {
    return new Promise(resolve => {
        chrome.storage.local.get([STORAGE_KEYS.state], data => {
            const next = {...(data[STORAGE_KEYS.state] || DEFAULT_STATE), ...patch};
            chrome.storage.local.set({[STORAGE_KEYS.state]: next}, () => resolve(next));
        });
    });
}

function getActions() {
    return new Promise(resolve => {
        chrome.storage.local.get([STORAGE_KEYS.actions], data => {
            resolve(data[STORAGE_KEYS.actions] || []);
        });
    });
}

function setActions(actions) {
    return new Promise(resolve => {
        chrome.storage.local.set({[STORAGE_KEYS.actions]: actions}, resolve);
    });
}

async function appendAction(action) {
    const actions = await getActions();
    // De-dupe consecutive identical events — clicks sometimes fire twice on
    // labels wrapping their input.
    const last = actions[actions.length - 1];
    if (last && last.op === action.op &&
        JSON.stringify(last.locator) === JSON.stringify(action.locator) &&
        last.value === action.value) {
        return actions;
    }
    actions.push(action);
    await setActions(actions);
    return actions;
}


// ---------------------------------------------------------------------
// Content-script injection
// ---------------------------------------------------------------------

async function injectIntoTab(tabId) {
    try {
        await chrome.scripting.executeScript({
            target: {tabId, allFrames: false},
            files: ["content.js"],
        });
    } catch (e) {
        // chrome:// URLs and the Web Store can't be scripted; surface but don't crash.
        console.warn("AbhiMate: couldn't inject into tab", tabId, e?.message);
    }
}


// ---------------------------------------------------------------------
// Message router (popup ↔ content ↔ background)
// ---------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    // We support a few message types — each is small enough to inline.
    (async () => {
        if (msg.type === "start-recording") {
            const tab = msg.tabId ?? (await chrome.tabs.query({active: true, currentWindow: true}))[0]?.id;
            await setActions([]);
            await setState({
                recording: true,
                tabId: tab,
                startedAt: Date.now(),
                feature: msg.feature || "",
                lastUrl: null,
            });
            if (tab) await injectIntoTab(tab);
            sendResponse({ok: true});
            return;
        }
        if (msg.type === "stop-recording") {
            const state = await setState({recording: false});
            const actions = await getActions();
            sendResponse({ok: true, state, actions});
            return;
        }
        if (msg.type === "get-status") {
            const [state, actions] = await Promise.all([getState(), getActions()]);
            sendResponse({state, actions});
            return;
        }
        if (msg.type === "clear-recording") {
            await setActions([]);
            await setState({...DEFAULT_STATE});
            sendResponse({ok: true});
            return;
        }
        if (msg.type === "recorded-action") {
            const state = await getState();
            if (!state.recording) { sendResponse({ok: false, reason: "not recording"}); return; }
            // Only accept events from the recording tab.
            if (sender.tab && state.tabId && sender.tab.id !== state.tabId) {
                sendResponse({ok: false, reason: "wrong tab"});
                return;
            }
            await appendAction(msg.action);
            sendResponse({ok: true});
            return;
        }
        sendResponse({ok: false, reason: "unknown message"});
    })();
    return true;  // tell Chrome we'll call sendResponse asynchronously
});


// ---------------------------------------------------------------------
// Navigation tracking — content scripts can't see top-frame nav, so the
// background listens and records goto events itself.
// ---------------------------------------------------------------------

chrome.webNavigation && chrome.webNavigation.onCommitted.addListener(async (details) => {
    if (details.frameId !== 0) return;     // top frame only
    const state = await getState();
    if (!state.recording || details.tabId !== state.tabId) return;
    if (details.url === state.lastUrl) return;
    await setState({lastUrl: details.url});
    await appendAction({op: "goto", url: details.url});
    // Re-inject the content script on every nav (the previous one is gone
    // once the new document loads).
    setTimeout(() => injectIntoTab(details.tabId), 50);
});
