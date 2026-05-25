// AbhiMate Recorder — content script (page-level listeners + locator builder).
//
// Runs inside the target page when recording is on. Captures:
//   * click   → emits "click" with the best locator we can build
//   * input   → emits "fill" with the current value, debounced per field
//   * change  → emits "select" for <select> dropdowns
//   * keydown → emits "press" for Enter / Escape (key flows)
//
// Locator priority (matches AbhiMate's GHERKIN_RULES):
//   id > testid > name > role > label > placeholder > text > css path
//
// The recorder is intentionally additive: it doesn't preventDefault on any
// event, doesn't change page styles beyond a thin hover outline, and
// removes its listeners cleanly when the background tells it to stop.

(() => {
    // Single-injection guard — chrome.scripting.executeScript injects again
    // after every nav, but the previous document is already gone so a fresh
    // closure each time is fine. We only need to avoid double-binding within
    // ONE document.
    if (window.__abhimateRecorderActive) return;
    window.__abhimateRecorderActive = true;

    const pendingFills = new WeakMap();   // input -> setTimeout id


    // -----------------------------------------------------------------
    // Locator builder
    // -----------------------------------------------------------------

    function safeAttr(el, name) {
        try { return el.getAttribute(name) || ""; } catch (_) { return ""; }
    }

    function visibleText(el) {
        try {
            const t = (el.innerText || el.textContent || "").trim();
            return t && t.length <= 80 ? t : "";
        } catch (_) { return ""; }
    }

    // Best-effort unique CSS selector. Walks up the tree, building a
    // ":nth-of-type(i)"-anchored path. Capped to ~5 levels so we don't
    // produce monsters like "body > div > div > div > div > div > div".
    function uniqueCss(el) {
        if (!(el instanceof Element)) return "";
        const parts = [];
        let cur = el;
        let levels = 0;
        while (cur && cur.nodeType === 1 && levels < 5) {
            let part = cur.tagName.toLowerCase();
            if (cur.id) {
                parts.unshift(`#${CSS.escape(cur.id)}`);
                break;
            }
            const cls = (cur.className && typeof cur.className === "string")
                ? cur.className.trim().split(/\s+/).filter(Boolean).slice(0, 2) : [];
            if (cls.length) part += "." + cls.map(c => CSS.escape(c)).join(".");
            const parent = cur.parentElement;
            if (parent) {
                const idx = Array.from(parent.children).indexOf(cur) + 1;
                part += `:nth-child(${idx})`;
            }
            parts.unshift(part);
            cur = cur.parentElement;
            levels += 1;
        }
        return parts.join(" > ");
    }

    function buildLocators(el) {
        // Return the primary + ordered fallbacks. AbhiMate's executor walks
        // the fallback chain on failure (Feature #9 — self-heal cache).
        const choices = [];
        const id = safeAttr(el, "id");
        const testid = safeAttr(el, "data-testid") || safeAttr(el, "data-test")
                       || safeAttr(el, "data-test-id");
        const name = safeAttr(el, "name");
        const role = safeAttr(el, "role");
        const ariaLabel = safeAttr(el, "aria-label");
        const placeholder = safeAttr(el, "placeholder");
        const text = visibleText(el);

        if (id)         choices.push({by: "id", value: id});
        if (testid)     choices.push({by: "testid", value: testid});
        if (name)       choices.push({by: "name", value: name});
        if (ariaLabel)  choices.push({by: "label", value: ariaLabel});
        if (role)       choices.push({by: "role", value: role});
        if (placeholder) choices.push({by: "placeholder", value: placeholder});
        if (text && ["button", "a", "summary", "label"].includes(el.tagName.toLowerCase())) {
            choices.push({by: "text", value: text});
        }
        const css = uniqueCss(el);
        if (css) choices.push({by: "css", value: css});

        if (!choices.length) return null;
        const primary = choices[0];
        const fallbacks = choices.slice(1, 4);   // cap at 3 fallbacks
        return {...primary, fallbacks};
    }


    // -----------------------------------------------------------------
    // Hover outline (visual feedback)
    // -----------------------------------------------------------------

    let lastHovered = null;

    function setHoverStyle(el, on) {
        if (!el || !el.style) return;
        if (on) {
            el.dataset.__abhimateHover = "1";
            el.style.outline = "2px solid #6366f1";
            el.style.outlineOffset = "1px";
        } else if (el.dataset.__abhimateHover) {
            el.style.outline = "";
            el.style.outlineOffset = "";
            delete el.dataset.__abhimateHover;
        }
    }

    function onMouseOver(ev) {
        const t = ev.target;
        if (t === lastHovered) return;
        setHoverStyle(lastHovered, false);
        lastHovered = (t instanceof Element) ? t : null;
        setHoverStyle(lastHovered, true);
    }


    // -----------------------------------------------------------------
    // Event handlers (record)
    // -----------------------------------------------------------------

    function emit(action) {
        try {
            chrome.runtime.sendMessage({type: "recorded-action", action});
        } catch (_) { /* extension reloaded; harmless */ }
    }

    function onClick(ev) {
        const el = ev.target;
        if (!(el instanceof Element)) return;
        // Ignore clicks INSIDE form fields — those become input/change events.
        if (["input", "textarea", "select"].includes(el.tagName.toLowerCase())) return;
        const loc = buildLocators(el);
        if (!loc) return;
        emit({op: "click", locator: loc});
    }

    function onInput(ev) {
        const el = ev.target;
        if (!(el instanceof HTMLInputElement) && !(el instanceof HTMLTextAreaElement)) return;
        // Skip password fields to avoid recording secrets into a downloadable file
        if (el.type === "password") return;
        const loc = buildLocators(el);
        if (!loc) return;
        // Debounce: only emit the FINAL value after the user stops typing for 350ms.
        const pending = pendingFills.get(el);
        if (pending) clearTimeout(pending);
        const t = setTimeout(() => {
            pendingFills.delete(el);
            emit({op: "fill", locator: loc, value: el.value});
        }, 350);
        pendingFills.set(el, t);
    }

    function onChange(ev) {
        const el = ev.target;
        if (!(el instanceof HTMLSelectElement)) return;
        const loc = buildLocators(el);
        if (!loc) return;
        emit({op: "select", locator: loc, value: el.value});
    }

    function onKeyDown(ev) {
        if (ev.key === "Enter" || ev.key === "Escape" || ev.key === "Tab") {
            emit({op: "press", value: ev.key});
        }
    }


    // -----------------------------------------------------------------
    // Wire up
    // -----------------------------------------------------------------

    document.addEventListener("click", onClick, true);
    document.addEventListener("input", onInput, true);
    document.addEventListener("change", onChange, true);
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("mouseover", onMouseOver, true);

    // Allow the background to stop us mid-document.
    chrome.runtime.onMessage.addListener((msg) => {
        if (msg.type === "stop-content-recording") {
            document.removeEventListener("click", onClick, true);
            document.removeEventListener("input", onInput, true);
            document.removeEventListener("change", onChange, true);
            document.removeEventListener("keydown", onKeyDown, true);
            document.removeEventListener("mouseover", onMouseOver, true);
            setHoverStyle(lastHovered, false);
            window.__abhimateRecorderActive = false;
        }
    });
})();
