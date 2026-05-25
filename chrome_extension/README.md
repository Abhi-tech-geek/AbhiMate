# AbhiMate Recorder (Chrome extension)

Record clicks, inputs, and navigation on any web page, then import the
result into AbhiMate as a runnable BDD session.

The output JSON uses the **same Action Plan vocabulary** AbhiMate's
executor already understands (`goto`, `click`, `fill`, `press`,
`select`, `assert_visible`, …). No translation layer — what you record
is what AbhiMate runs.

---

## Install (developer mode)

1. Open `chrome://extensions/` in Chrome (or Edge, Brave — anything
   Chromium-based).
2. Toggle **Developer mode** on (top-right).
3. Click **Load unpacked** and select this `chrome_extension/` folder.
4. The "AbhiMate Recorder" icon appears in the toolbar. Pin it.

No external dependencies, no npm install, no build step. Manifest v3,
service-worker-based.

## Use

1. Click the extension icon. (Optional) type a feature name like
   "Login flow" — it becomes the AbhiMate session title.
2. Hit **● Start recording**.
3. Switch to the tab you want to capture. Click through the flow,
   type into inputs, navigate — the recorder logs everything in the
   background.
4. Open the popup again. Hit **■ Stop recording**. The action list
   is shown for a quick sanity check.
5. **⤓ Download recording** to get a `.abhimate.json` file
   (or **Copy to clipboard** if you'd rather paste).
6. Open AbhiMate → on the welcome screen, click **📥 Import recording**
   (or drag the JSON onto the chat input). The session is created and
   loaded immediately. Now you can edit, schedule, or run it like any
   other AbhiMate session.

## What gets recorded

| Page event | Recorded op | Locator strategy |
|---|---|---|
| `click` on button / link / element | `click` | id → testid → name → label → role → text → css |
| `input` on text field / textarea | `fill` (debounced 350 ms) | same priority |
| `change` on `<select>` | `select` | same priority |
| `keydown` Enter / Escape / Tab | `press` | — |
| Top-frame navigation | `goto` | — |

**Password inputs are skipped** — we don't want secrets sitting in a
downloadable JSON file. Fill those in by editing the case in AbhiMate
after import (or wire them through your secrets manager).

## What does NOT get recorded (yet)

* Drag-and-drop interactions
* File uploads
* iframe / shadow-DOM interactions
* Hover-only flows (hover IS captured visually but not emitted as a
  step — AbhiMate's hover op exists if you need it; add it by hand)
* Right-click / context menu

## Locator quality tips

The extension produces an ordered **fallback chain** for every locator
(`id` first, then `testid`, then `name` …) — AbhiMate's self-heal
layer (Feature #9) will promote a working fallback to primary on the
second run. So a brittle CSS path doesn't mean the test breaks the
next time the markup shifts a little.

If your app uses `data-testid` consistently, recordings stay rock-solid
across redeploys. If you rely on visible text, watch out for i18n
flips.

## Safety notes

* The extension never POSTs to a remote server. Everything stays
  local until you upload the JSON yourself.
* `host_permissions: ["<all_urls>"]` is needed so the content script
  can attach to any page you visit. The script is **only injected
  when you actively press Start recording** — never passively.
* Storage uses `chrome.storage.local` — recordings are sandboxed to
  your profile, never synced.

## Troubleshooting

**"Nothing got recorded after I navigated."**
The new page reloads the content script. The background worker
re-injects it within ~50 ms of the nav event — give it a moment, then
look at the popup's action list. If it still didn't pick up, the
target page might be a `chrome://` URL or a sandboxed PDF viewer where
extensions can't run.

**"My recording has duplicate clicks."**
The recorder de-dupes consecutive identical events, but `<label>`s
wrapping their input can still produce two distinct event targets —
edit the case in AbhiMate and remove the duplicate.

**"The session won't import — quota exceeded."**
You're at the 5-session cap. Delete an unused session in the AbhiMate
sidebar, then drag the JSON in again.
