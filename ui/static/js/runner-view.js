// --- runner-view.js — generate + SSE + render + triage + automation + reports ---
// -------------------------------------------------------------
// UNIFIED INTELLIGENT SMART GENERATE
// -------------------------------------------------------------
generateBtn.addEventListener('click', async () => {
    const text = featureInput.value.trim();
    if(!text) return;

    welcomeState.classList.add('hidden');
    activeSessionState.classList.remove('hidden');
    activeSessionTitle.innerText = text;
    activeSessionStatus.innerText = "PIPELINE RUNNING (MULTI-AGENT ENABLED)";
    automationPrompt.classList.add('hidden');

    // Loading state: disable button + spinner + skeleton cards
    generateBtn.disabled = true;
    const originalBtnHtml = generateBtn.innerHTML;
    generateBtn.innerHTML = '<span class="spinner" aria-label="loading"></span>';
    const count = parseInt(caseCountSelect ? caseCountSelect.value : '8', 10) || 8;
    showSkeletonCards(testCasesContainer, Math.min(count, 5));
    featureInput.value = '';

    const payload = {
        prompt: text,
        autoRun: autoExecuteCheck.checked,
        environment: envSelect.value,
        model: modelSelect.value,
        lang: langSelect.value,
        count: count
    };

    try {
        const res = await fetch('/api/smart_input', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const data = await res.json().catch(() => ({}));
        // 401 with code=llm_unavailable is a key problem, NOT a logout.
        if (res.status === 401 && data.code === 'llm_unavailable') {
            handleLlmConfigError(data);
            throw new Error(data.error || 'LLM unavailable');
        }
        if (res.status === 401) { window.location.href = '/login'; return; }
        if (res.status === 409) {
            if (data.quota) { window.__quota = data.quota; if (typeof renderQuota === 'function') renderQuota(); }
            toast(data.error || 'Session limit reached. Delete one first.',
                  'warn', 'Session quota full');
            throw new Error(data.error || 'Session quota full');
        }
        if(data.error) throw new Error(data.error);

        currentSessionId = data.session.session_id;
        activeSessionStatus.innerText = data.session.state;
        renderTestCases(data.session.test_cases, testCasesContainer);

        if(data.session.state === "EXECUTED" && data.session.report) {
            renderReportInline(data.session.report, testCasesContainer);
        } else {
            automationPrompt.classList.remove('hidden');
        }

        loadSessions();
        loadGlobalInsights();
    } catch (err) {
        testCasesContainer.replaceChildren();
        testCasesContainer.insertAdjacentHTML('beforeend',
            `<p style="color:var(--fail)">${escapeHtml(err.message)}</p>`);
    } finally {
        generateBtn.disabled = false;
        generateBtn.innerHTML = originalBtnHtml;
    }
});

// ---------- Phase 3: streaming execution via SSE ----------
var __currentRunId = null;
var __currentEventSource = null;

var selectAllBtn = document.getElementById('selectAllBtn');
var selectNoneBtn = document.getElementById('selectNoneBtn');
var cancelRunBtn = document.getElementById('cancelRunBtn');
var runProgressBox = document.getElementById('runProgress');
var progressFill = document.getElementById('progressFill');
var progressLabel = document.getElementById('progressLabel');

if (selectAllBtn) {
    selectAllBtn.addEventListener('click', () => {
        document.querySelectorAll('.tc-checkbox').forEach(cb => {
            if (!cb.checked) { cb.checked = true; cb.dispatchEvent(new Event('change')); }
        });
    });
}
if (selectNoneBtn) {
    selectNoneBtn.addEventListener('click', () => {
        document.querySelectorAll('.tc-checkbox').forEach(cb => {
            if (cb.checked) { cb.checked = false; cb.dispatchEvent(new Event('change')); }
        });
    });
}
if (cancelRunBtn) {
    cancelRunBtn.addEventListener('click', async () => {
        if (!__currentRunId) return;
        try {
            await fetch(`/api/runs/${__currentRunId}/cancel`, { method: 'POST' });
            progressLabel.innerText = 'Cancel requested — finishing current case…';
        } catch (_) {}
    });
}

function setRunControls(running) {
    cancelRunBtn.classList.toggle('hidden', !running);
    runAutomationBtn.disabled = running;
    if (selectAllBtn) selectAllBtn.disabled = running;
    if (selectNoneBtn) selectNoneBtn.disabled = running;
    runProgressBox.classList.toggle('hidden', !running);
    if (!running) {
        progressFill.style.width = '0%';
        progressLabel.innerText = '';
    }
}

runAutomationBtn.addEventListener('click', () => {
    if (!currentSessionId) return;
    const remaining = (currentCases() || []).filter(c => !c.user_skipped);
    if (remaining.length === 0) {
        toast('Tick at least one case before running.', 'warn', 'No cases selected');
        return;
    }
    activeSessionStatus.innerText = 'EXECUTING…';
    setRunControls(true);

    let total = remaining.length;
    let done = 0;

    // SSE GET stream — EventSource cannot POST, so the server reads env separately
    // via the parallel /api/execute_stream POST below. (Phase A will refactor to a
    // proper start+stream split when we move off Selenium.)
    const deviceEl = document.getElementById('deviceSelect');
    const devicePref = (deviceEl && deviceEl.value) ||
                       (window.__deviceOverride || 'Desktop');

    const workersEl = document.getElementById('workersSelect');
    const workers = workersEl ? parseInt(workersEl.value, 10) || 1 : 1;

    fetch(`/api/execute_stream/${currentSessionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            environment: envSelect.value,
            device: devicePref,
            workers: workers,
        })
    }).then(async resp => {
        if (!resp.ok || !resp.body) {
            const text = await resp.text();
            progressLabel.innerText = 'Failed to start: ' + text.slice(0, 200);
            setRunControls(false);
            return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        const consume = ({ done: streamDone, value }) => {
            if (streamDone) { setRunControls(false); return; }
            buf += decoder.decode(value, { stream: true });
            const parts = buf.split('\n\n');
            buf = parts.pop();
            parts.forEach(chunk => {
                const line = chunk.split('\n').find(l => l.startsWith('data:'));
                if (!line) return;
                let msg;
                try { msg = JSON.parse(line.slice(5).trim()); } catch (_) { return; }
                handleStreamEvent(msg);
            });
            return reader.read().then(consume);
        };
        reader.read().then(consume);
    }).catch(err => {
        progressLabel.innerText = 'Error: ' + err.message;
        setRunControls(false);
    });

    function handleStreamEvent(msg) {
        if (msg.type === 'run_id') {
            __currentRunId = msg.run_id;
        } else if (msg.type === 'start') {
            total = msg.total || total;
            const parallelTag = (msg.workers && msg.workers > 1)
                ? ` · ${msg.workers} workers in parallel` : '';
            progressLabel.innerText = `0 / ${total}${parallelTag}`;
        } else if (msg.type === 'case_start') {
            const card = document.querySelector(`.test-case-card[data-case="${msg.id}"]`);
            if (card) {
                card.classList.add('is-running');
                if (typeof msg.worker_id === 'number') {
                    card.dataset.worker = String(msg.worker_id);
                }
                // Bring the active case into view, but be polite about it.
                // Skip scrollIntoView in parallel mode — fighting workers
                // make the page jitter wildly.
                if (typeof msg.worker_id !== 'number') {
                    try { card.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (_) {}
                }
            }
            const r = document.getElementById(`running-${msg.id}`);
            if (r) r.classList.remove('hidden');
            const workerTag = (typeof msg.worker_id === 'number')
                ? ` (worker ${msg.worker_id + 1})` : '';
            progressLabel.innerText = `Running ${msg.id}${workerTag} — ${done + 1} / ${total}`;
        } else if (msg.type === 'case_done') {
            const card = document.querySelector(`.test-case-card[data-case="${msg.id}"]`);
            if (card) card.classList.remove('is-running');
            const r = document.getElementById(`running-${msg.id}`);
            if (r) r.classList.add('hidden');
            const tc = findCase(msg.id);
            if (tc) {
                tc.status = msg.status; tc.error = msg.error; tc.screenshot = msg.screenshot;
            }
            done += 1;
            const pct = (done / Math.max(total, 1)) * 100;
            progressFill.style.width = pct.toFixed(1) + '%';
            const pb = document.getElementById('progressBar');
            if (pb) pb.setAttribute('aria-valuenow', String(Math.round(pct)));
            progressLabel.innerText = `${done} / ${total} complete`;
        } else if (msg.type === 'cancelled') {
            progressLabel.innerText = `Cancelled. ${msg.remaining || 0} case(s) skipped.`;
        } else if (msg.type === 'session_saved') {
            const session = msg.session;
            activeSessionStatus.innerText = session.state;
            setCurrentCases(session.test_cases);
            renderTestCases(session.test_cases, testCasesContainer);
            if (session.report) renderReportInline(session.report, testCasesContainer);
            loadGlobalInsights();
            loadSessions();
            __currentRunId = null;
            setRunControls(false);
        } else if (msg.type === 'error') {
            progressLabel.innerText = 'Error: ' + (msg.message || 'unknown');
            setRunControls(false);
        }
    }
});

// Wire Suggest Fix modal close + apply
document.addEventListener('DOMContentLoaded', () => {
    const modal = document.getElementById('fixModal');
    if (!modal) return;
    modal.querySelector('.modal-close').addEventListener('click', closeSuggestFix);
    document.getElementById('fixCancelBtn').addEventListener('click', closeSuggestFix);
    document.getElementById('fixApplyBtn').addEventListener('click', applyFixAndRetry);
    modal.addEventListener('click', (e) => { if (e.target === modal) closeSuggestFix(); });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) closeSuggestFix();
    });
});


// Rendering UI
function renderTestCases(cases, containerElement) {
    setCurrentCases(cases);
    if (!cases || cases.length === 0) {
        containerElement.replaceChildren();
        containerElement.insertAdjacentHTML('beforeend', '<p style="color:var(--text-secondary)">No test cases generated.</p>');
        return;
    }
    containerElement.replaceChildren();
    cases.forEach((tc, idx) => {
        const statusBadge = tc.status === 'Pass' ? '<span style="color:var(--pass)">[PASS]</span>'
                          : tc.status === 'Fail' ? '<span style="color:var(--fail)">[FAIL]</span>'
                          : tc.status === 'Blocked' ? '<span style="color:#facc15">[BLOCKED]</span>'
                          : `<span style="color:var(--text-secondary)">[${escapeHtml(tc.status || 'Un-Run')}]</span>`;

        const tagsHtml = (tc.tags || []).map(t => {
            const lt = t.toLowerCase();
            const cls = lt.includes('security') ? 'tag-security'
                      : lt.includes('api') ? 'tag-api'
                      : lt.includes('smoke') ? 'tag-smoke' : '';
            return `<span class="tag-chip ${cls}">${escapeHtml(t)}</span>`;
        }).join('');

        const gherkinHtml = renderGherkinSteps(tc);
        const errorHtml = tc.error ? `<div style="color:var(--fail); margin-top:10px; font-size:0.9rem;"><strong>Error:</strong> ${escapeHtml(tc.error)}</div>` : '';
        const screenshotHtml = (tc.status === 'Fail' && tc.screenshot) ? `
            <div class="failure-screenshot">
                <img src="/${escapeHtml(tc.screenshot)}" alt="Failure screenshot for ${escapeHtml(tc.id)}" onclick="openLightbox(this.src)">
            </div>` : '';

        // Visual regression artifacts: baseline | actual | diff for any
        // failed assert_visual_match. The image URLs go through the
        // user-scoped /api/visual/image endpoint.
        const failedVisuals = (tc.visual_artifacts || []).filter(v => v.kind === 'diff' && v.status === 'failed');
        const visualArtifactsHtml = failedVisuals.length ? `
            <div class="visual-diff-strip">
                ${failedVisuals.map(v => {
                    const n = encodeURIComponent(v.name);
                    const pct = (typeof v.diff_percent === 'number') ? v.diff_percent.toFixed(2) + '% changed' : '';
                    return `
                    <div class="visual-diff-row">
                        <div class="visual-diff-head">
                            <strong>${escapeHtml(v.name)}</strong>
                            <span class="visual-diff-meta">${pct}</span>
                        </div>
                        <div class="visual-diff-thumbs">
                            <figure>
                                <img src="/api/visual/image?kind=baseline&name=${n}" alt="baseline"
                                     onclick="openLightbox(this.src)" loading="lazy">
                                <figcaption>baseline</figcaption>
                            </figure>
                            <figure>
                                <img src="/api/visual/image?kind=actual&name=${n}" alt="actual"
                                     onclick="openLightbox(this.src)" loading="lazy">
                                <figcaption>actual</figcaption>
                            </figure>
                            <figure>
                                <img src="/api/visual/image?kind=diff&name=${n}" alt="diff"
                                     onclick="openLightbox(this.src)" loading="lazy">
                                <figcaption>diff</figcaption>
                            </figure>
                        </div>
                    </div>`;
                }).join('')}
            </div>` : '';
        const aiInsight = tc.bug_insight ? `<div style="background:rgba(239,68,68,0.08); padding:10px; border-left:3px solid var(--fail); margin-top:10px; font-size:0.9rem; border-radius:0 6px 6px 0;"><strong>AI Root Cause:</strong> ${escapeHtml(tc.bug_insight)}</div>` : '';

        const codeId = `code-${tc.id}-${idx}`;
        const codeBlock = tc.selenium_action ? `
            <details style="margin-top:12px;">
                <summary style="cursor:pointer; color:var(--accent); font-size:0.85rem; user-select:none;">View executable Python</summary>
                <div class="code-wrap">
                    <button class="copy-btn" data-target="${codeId}">Copy</button>
                    <pre><code id="${codeId}" class="language-python">${escapeHtml(tc.selenium_action)}</code></pre>
                </div>
            </details>` : '';

        const scenarioLine = tc.scenario ? `<div style="color:var(--text-secondary); font-size:0.85rem; margin-top:4px;">${escapeHtml(tc.scenario)}</div>` : '';

        const isSkipped = !!tc.user_skipped;
        const isKnown = !!tc.known_issue;
        const isFailed = tc.status === 'Fail';
        const cardCls = ['test-case-card'];
        if (isSkipped) cardCls.push('is-skipped');
        if (isKnown) cardCls.push('is-known');

        const actionsHtml = `
            <div class="tc-actions">
                <button class="mini-btn accent" data-act="edit" data-case="${escapeHtml(tc.id)}">Edit code</button>
                ${isFailed ? `<button class="mini-btn warn" data-act="suggest" data-case="${escapeHtml(tc.id)}">Suggest fix</button>` : ''}
                ${isFailed ? `<button class="mini-btn accent" data-act="deep-dive" data-case="${escapeHtml(tc.id)}" title="Multi-paragraph AI diagnosis using trace + history">Why did it fail?</button>` : ''}
                ${isFailed ? `<button class="mini-btn warn" data-act="create-ticket" data-case="${escapeHtml(tc.id)}" title="File this failure as a JIRA or Linear ticket">Create ticket</button>` : ''}
                ${isFailed ? `<button class="mini-btn accent" data-act="retry" data-case="${escapeHtml(tc.id)}">Retry</button>` : ''}
                ${isFailed ? `<button class="mini-btn warn" data-act="mark-known" data-case="${escapeHtml(tc.id)}">${isKnown ? 'Unmark known' : 'Mark known'}</button>` : ''}
            </div>
            <div class="code-edit-host hidden" id="edit-host-${escapeHtml(tc.id)}"></div>
        `;

        const cardHtml = `
            <div class="${cardCls.join(' ')}" data-case="${escapeHtml(tc.id)}">
                <div class="tc-select-row">
                    <input type="checkbox" class="tc-checkbox" data-case="${escapeHtml(tc.id)}" ${isSkipped ? '' : 'checked'}>
                    <strong>${escapeHtml(tc.id)}</strong>
                    <span class="tc-type">${escapeHtml(tc.type)}</span>
                    ${statusBadge}
                    <span class="tc-running hidden" id="running-${escapeHtml(tc.id)}"><span class="spinner"></span> running…</span>
                </div>
                <div class="tc-desc">${escapeHtml(tc.description)}</div>
                ${scenarioLine}
                ${tagsHtml ? `<div class="tc-tags">${tagsHtml}</div>` : ''}
                ${gherkinHtml}
                <div style="font-size:0.9rem; margin-top:10px;"><strong>Expected:</strong> ${escapeHtml(tc.expected)}</div>
                ${errorHtml}
                ${aiInsight}
                ${screenshotHtml}
                ${visualArtifactsHtml}
                ${codeBlock}
                ${actionsHtml}
            </div>
        `;
        containerElement.insertAdjacentHTML('beforeend', cardHtml);
    });

    containerElement.querySelectorAll('.copy-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const target = document.getElementById(btn.dataset.target);
            if (!target) return;
            navigator.clipboard.writeText(target.innerText).then(() => {
                btn.classList.add('copied');
                btn.textContent = 'Copied!';
                setTimeout(() => { btn.classList.remove('copied'); btn.textContent = 'Copy'; }, 1500);
            });
        });
    });

    containerElement.querySelectorAll('.tc-checkbox').forEach(cb => {
        cb.addEventListener('change', () => onCaseSkipToggle(cb.dataset.case, !cb.checked));
    });

    containerElement.querySelectorAll('.tc-actions .mini-btn').forEach(btn => {
        const act = btn.dataset.act;
        const caseId = btn.dataset.case;
        btn.addEventListener('click', () => {
            if (act === 'edit') toggleEditCase(caseId);
            else if (act === 'suggest') openSuggestFix(caseId);
            else if (act === 'retry') retryCase(caseId);
            else if (act === 'mark-known') toggleMarkKnown(caseId, btn);
            else if (act === 'deep-dive') openDeepDive(caseId);
            else if (act === 'create-ticket') openCreateTicket(caseId);
        });
    });

    if (window.Prism) {
        try { window.Prism.highlightAllUnder(containerElement); } catch (_) {}
    }
}

function renderGherkinSteps(tc) {
    const steps = tc.gherkin_steps && tc.gherkin_steps.length ? tc.gherkin_steps : null;
    if (!steps) {
        if (!tc.steps || !tc.steps.length) return '';
        const lines = tc.steps.map(s => `<span class="gherkin-line">${escapeHtml(s)}</span>`).join('');
        return `<div class="gherkin-block">${lines}</div>`;
    }
    const kwClass = { Given: 'gw-given', When: 'gw-when', Then: 'gw-then', And: 'gw-and', But: 'gw-but' };
    const lines = steps.map(s => {
        const cls = kwClass[s.keyword] || 'gw-keyword';
        return `<span class="gherkin-line"><span class="gw-keyword ${cls}">${escapeHtml(s.keyword)}</span> ${escapeHtml(s.text)}</span>`;
    }).join('');
    return `<div class="gherkin-block">${lines}</div>`;
}

// ---------- Phase 3: per-case state mutations ----------

function currentCases() { return window.__currentCases || []; }
function setCurrentCases(cases) { window.__currentCases = cases || []; }
function findCase(caseId) { return currentCases().find(c => c.id === caseId); }

async function onCaseSkipToggle(caseId, isSkipped) {
    if (!currentSessionId) return;
    const tc = findCase(caseId);
    if (tc) tc.user_skipped = isSkipped;
    const card = document.querySelector(`.test-case-card[data-case="${caseId}"]`);
    if (card) card.classList.toggle('is-skipped', isSkipped);
    try {
        await fetch(`/api/cases/${currentSessionId}/${caseId}/update`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ user_skipped: isSkipped })
        });
    } catch (_) {}
}

function toggleEditCase(caseId) {
    const host = document.getElementById(`edit-host-${caseId}`);
    if (!host) return;
    if (!host.classList.contains('hidden')) {
        host.classList.add('hidden');
        host.replaceChildren();
        return;
    }
    const tc = findCase(caseId);
    if (!tc) return;
    host.replaceChildren();
    host.insertAdjacentHTML('beforeend', `
        <p class="modal-label" style="margin-top:10px;">Selenium snippet</p>
        <textarea class="code-edit-area" id="edit-area-${caseId}" spellcheck="false">${escapeHtml(tc.selenium_action || '')}</textarea>
        <div class="code-edit-controls">
            <button class="mini-btn" data-cancel-edit="${caseId}">Cancel</button>
            <button class="mini-btn accent" data-save-edit="${caseId}">Save</button>
        </div>
    `);
    host.classList.remove('hidden');
    host.querySelector(`[data-cancel-edit="${caseId}"]`).addEventListener('click', () => toggleEditCase(caseId));
    host.querySelector(`[data-save-edit="${caseId}"]`).addEventListener('click', () => saveCaseEdit(caseId));
}

async function saveCaseEdit(caseId) {
    if (!currentSessionId) return;
    const ta = document.getElementById(`edit-area-${caseId}`);
    if (!ta) return;
    const code = ta.value;
    try {
        const res = await fetch(`/api/cases/${currentSessionId}/${caseId}/update`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ selenium_action: code })
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        const tc = findCase(caseId);
        if (tc) tc.selenium_action = code;
        toggleEditCase(caseId);
        renderTestCases(currentCases(), testCasesContainer);
    } catch (err) {
        toast(err.message, 'error', 'Save failed');
    }
}

async function toggleMarkKnown(caseId) {
    if (!currentSessionId) return;
    const tc = findCase(caseId);
    const next = !(tc && tc.known_issue);
    try {
        await fetch(`/api/cases/${currentSessionId}/${caseId}/mark_known`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ known: next })
        });
        if (tc) tc.known_issue = next;
        renderTestCases(currentCases(), testCasesContainer);
    } catch (err) { toast(err.message, 'error'); }
}

// ---------- Suggest Fix modal ----------

var __fixTargetCase = null;

function openSuggestFix(caseId) {
    const tc = findCase(caseId);
    if (!tc) return;
    __fixTargetCase = caseId;
    document.getElementById('fixModalTitle').innerText = `Suggest a fix for ${caseId}`;
    document.getElementById('fixModalLoading').classList.remove('hidden');
    document.getElementById('fixModalContent').classList.add('hidden');
    document.getElementById('fixApplyBtn').disabled = true;
    document.getElementById('fixModal').classList.remove('hidden');

    fetch('/api/suggest_fix', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            test_id: tc.id,
            description: tc.description,
            error: tc.error || '',
            expected: tc.expected || '',
            selenium_action: tc.selenium_action || ''
        })
    }).then(r => r.json()).then(data => {
        document.getElementById('fixModalLoading').classList.add('hidden');
        document.getElementById('fixModalContent').classList.remove('hidden');
        document.getElementById('fixExplanation').innerText = data.explanation || '(no explanation returned)';
        document.getElementById('fixCodeArea').value = data.suggested_code || tc.selenium_action || '';
        document.getElementById('fixApplyBtn').disabled = false;
    }).catch(err => {
        document.getElementById('fixModalLoading').innerText = 'Failed to fetch suggestion: ' + err.message;
    });
}

function closeSuggestFix() {
    document.getElementById('fixModal').classList.add('hidden');
    __fixTargetCase = null;
}

async function applyFixAndRetry() {
    if (!__fixTargetCase || !currentSessionId) return;
    const newCode = document.getElementById('fixCodeArea').value;
    const caseId = __fixTargetCase;
    closeSuggestFix();
    await retryCase(caseId, newCode);
}

async function retryCase(caseId, newCode) {
    if (!currentSessionId) return;
    const running = document.getElementById(`running-${caseId}`);
    if (running) running.classList.remove('hidden');
    try {
        const res = await fetch(`/api/cases/${currentSessionId}/${caseId}/retry`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                selenium_action: newCode,
                environment: envSelect.value
            })
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        const updated = data.case;
        if (updated) {
            const cases = currentCases();
            const idx = cases.findIndex(c => c.id === caseId);
            if (idx >= 0) cases[idx] = updated;
            setCurrentCases(cases);
            renderTestCases(cases, testCasesContainer);
        }
        loadGlobalInsights();
    } catch (err) {
        toast(err.message, 'error', 'Retry failed');
        if (running) running.classList.add('hidden');
    }
}

function renderGherkinSteps(tc) {
    // Prefer structured gherkin_steps; fall back to legacy plain steps array.
    const steps = tc.gherkin_steps && tc.gherkin_steps.length ? tc.gherkin_steps : null;
    if (!steps) {
        if (!tc.steps || !tc.steps.length) return '';
        const lines = tc.steps.map(s => `<span class="gherkin-line">${escapeHtml(s)}</span>`).join('');
        return `<div class="gherkin-block">${lines}</div>`;
    }
    const kwClass = { Given: 'gw-given', When: 'gw-when', Then: 'gw-then', And: 'gw-and', But: 'gw-but' };
    const lines = steps.map(s => {
        const cls = kwClass[s.keyword] || 'gw-keyword';
        return `<span class="gherkin-line"><span class="gw-keyword ${cls}">${escapeHtml(s.keyword)}</span> ${escapeHtml(s.text)}</span>`;
    }).join('');
    return `<div class="gherkin-block">${lines}</div>`;
}

function renderReportInline(report, containerElement) {
    const html = `
        <div style="background:var(--bg-panel); border:1px solid var(--glass-border); padding:1.5rem; border-radius:12px; margin-top:2rem;">
            <h3 style="color:var(--accent); margin-bottom:15px;">Reporting Agent Summary</h3>
            <div style="display:flex; gap:20px; margin-bottom:15px;">
                <div style="font-size:1.5rem; font-weight:bold;">Total: ${report.metrics.total}</div>
                <div style="font-size:1.5rem; font-weight:bold; color:var(--pass);">Pass: ${report.metrics.passed}</div>
                <div style="font-size:1.5rem; font-weight:bold; color:var(--fail);">Fail: ${report.metrics.failed}</div>
            </div>
            <p>${report.executive_summary}</p>
        </div>
    `;
    containerElement.insertAdjacentHTML('beforeend', html);
}

// Reports View Logic
var reportSessionSelect = document.getElementById('reportSessionSelect');

async function initReportsDashboard() {
    reportSessionSelect.replaceChildren();
    reportSessionSelect.insertAdjacentHTML('beforeend',
        '<option value="">-- Loading Sessions... --</option>');
    document.getElementById('reportEmptyState').classList.remove('hidden');
    document.getElementById('reportContentArea').classList.add('hidden');

    try {
        const res = await fetch('/api/sessions');
        const sessions = await res.json();
        const executed = sessions.filter(s => s.state === 'EXECUTED');

        reportSessionSelect.replaceChildren();
        reportSessionSelect.insertAdjacentHTML('beforeend',
            '<option value="">-- Select an Executed Session --</option>');
        executed.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.session_id;
            opt.innerText = `${s.feature} (${new Date(s.timestamp*1000).toLocaleString()})`;
            reportSessionSelect.appendChild(opt);
        });

        // Auto-load the latest executed session (sessions sorted desc by timestamp).
        if (executed.length > 0) {
            reportSessionSelect.value = executed[0].session_id;
            reportSessionSelect.dispatchEvent(new Event('change'));
        }
    } catch(err) {
        reportSessionSelect.replaceChildren();
        reportSessionSelect.insertAdjacentHTML('beforeend',
            '<option value="">-- Failed to Load --</option>');
    }
}

reportSessionSelect.addEventListener('change', async (e) => {
    const sessionId = e.target.value;
    if(!sessionId) {
        document.getElementById('reportEmptyState').classList.remove('hidden');
        document.getElementById('reportContentArea').classList.add('hidden');
        return;
    }
    
    document.getElementById('reportEmptyState').classList.add('hidden');
    document.getElementById('reportContentArea').classList.remove('hidden');
    
    document.getElementById('rSummary').innerText = "Analyzing payload...";
    document.getElementById('rLogsList').innerHTML = "";
    
    const healthCtx = document.getElementById('healthChart');
    if(window.healthChartInstance) window.healthChartInstance.destroy();
    
    try {
        const res = await fetch(`/api/sessions/${sessionId}`);
        const session = await res.json();
        const report = session.report;
        
        if(!report) throw new Error("No report generated for this session.");
        
        window.healthChartInstance = new Chart(healthCtx, {
            type: 'doughnut',
            data: {
                labels: ['Passed', 'Failed'],
                datasets: [{
                    data: [report.metrics.passed, report.metrics.failed],
                    backgroundColor: ['#4ade80', '#ef4444'],
                    borderColor: '#121212',
                    borderWidth: 2
                }]
            },
            options: { cutout: '75%', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
        });
        
        document.getElementById('rSummary').innerText = report.executive_summary || "No insights created.";
        
        const fContainer = document.getElementById('rLogsList');
        const failedCases = session.test_cases.filter(tc => tc.status === 'Fail');
        
        if(failedCases.length === 0) {
            fContainer.innerHTML = '<li style="color:var(--text-secondary)">No failures detected. System passes 100% stable parameters.</li>';
        } else {
            failedCases.forEach(fc => {
                fContainer.insertAdjacentHTML('beforeend', `
                    <li style="background:rgba(255,255,255,0.05); padding:10px; border-left:3px solid var(--fail); margin-bottom:10px;">
                        <strong>${fc.id}</strong><br>
                        <span style="color:var(--text-secondary); font-size:0.85rem">Error: ${fc.error}</span><br>
                        <span style="color:var(--accent); font-size:0.85rem">AI Root Cause Agent Insight: ${fc.bug_insight}</span>
                    </li>
                `);
            });
        }
    } catch(err) {
        document.getElementById('rSummary').innerText = "Critical load issue: " + err.message;
    }
});

// -----------------------------------------
// Unified Automation Pipeline (Text + File)
// -----------------------------------------
var unifiedTextInput = document.getElementById('unifiedTextInput');
var unifiedFileInput = document.getElementById('unifiedFileInput');
var runUnifiedAutoBtn = document.getElementById('runUnifiedAutoBtn');
var unifiedAutoStatus = document.getElementById('unifiedAutoStatus');

runUnifiedAutoBtn.addEventListener('click', async () => {
    unifiedAutoStatus.innerText = "";
    runUnifiedAutoBtn.disabled = true;
    automationResultsContainer.classList.add('hidden');
    automationResultsContainer.innerHTML = '<p style="color:var(--text-secondary)">Executing via direct pipeline...</p>';

    // Check File Upload First
    if (unifiedFileInput.files.length > 0) {
        const file = unifiedFileInput.files[0];
        const reader = new FileReader();

        reader.onload = async (e) => {
            const csvPayload = e.target.result.trim();
            if (!csvPayload) {
                unifiedAutoStatus.style.color = "var(--fail)";
                unifiedAutoStatus.innerText = "Error: CSV file is empty.";
                runUnifiedAutoBtn.disabled = false;
                return;
            }
            unifiedAutoStatus.style.color = "var(--accent)";
            unifiedAutoStatus.innerText = "DataDrivenTestingAgent parsing CSV file mapping...";
            
            try {
                const res = await fetch('/api/data_driven', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ csv: csvPayload, environment: envSelect.value })
                });
                const data = await res.json();
                if(data.error) throw new Error(data.error);
                
                unifiedAutoStatus.style.color = "var(--pass)";
                unifiedAutoStatus.innerText = data.message;
            } catch (err) {
                unifiedAutoStatus.style.color = "var(--fail)";
                unifiedAutoStatus.innerText = "Execution failed: " + err.message;
            } finally {
                runUnifiedAutoBtn.disabled = false;
                setTimeout(() => unifiedAutoStatus.innerText = "", 5000);
            }
        };
        reader.readAsText(file);
        return;
    }

    // No file -> fallback to text input
    const rawVal = unifiedTextInput.value.trim();
    if (!rawVal) {
        unifiedAutoStatus.style.color = "var(--fail)";
        unifiedAutoStatus.innerText = "Please provide plain text instructions or upload a CSV file.";
        runUnifiedAutoBtn.disabled = false;
        setTimeout(() => unifiedAutoStatus.innerText = "", 3000);
        return;
    }

    unifiedAutoStatus.style.color = "var(--accent)";
    unifiedAutoStatus.innerText = "Processing automation execution directly pipeline...";
    automationResultsContainer.classList.remove('hidden');
    
    try {
        const payload = {
            prompt: rawVal,
            autoRun: true,
            environment: envSelect.value,
            model: modelSelect.value,
            lang: langSelect.value
        };

        const res = await fetch('/api/smart_input', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.status === 401 && data.code === 'llm_unavailable') {
            handleLlmConfigError(data);
            throw new Error(data.error || 'LLM unavailable');
        }
        if(data.error) throw new Error(data.error);

        unifiedAutoStatus.style.color = "var(--pass)";
        unifiedAutoStatus.innerText = "Pipeline ran successfully.";

        // Render IN-PLACE instead of jumping UI to dashboard
        renderTestCases(data.session.test_cases, automationResultsContainer);
        if(data.session.report) {
            renderReportInline(data.session.report, automationResultsContainer);
        }

        loadSessions(); // Updates sidebar history list
        loadGlobalInsights();
    } catch (err) {
        unifiedAutoStatus.style.color = "var(--fail)";
        unifiedAutoStatus.innerText = "Execution failed: " + err.message;
        automationResultsContainer.replaceChildren();
        automationResultsContainer.insertAdjacentHTML('beforeend',
            `<div class="error-panel">
                <strong>Could not run the pipeline.</strong>
                <p>${escapeHtml(err.message)}</p>
                <p class="error-hint">Check the LLM key banner at the top of the page, or visit Settings.</p>
             </div>`);
    } finally {
        runUnifiedAutoBtn.disabled = false;
    }
});

// =============================================================
// LLM key health banner — runs on load + after a 401 response
// =============================================================
function handleLlmConfigError(payload) {
    showLlmBanner(payload.error || 'LLM unavailable', payload.hint || '');
    toast(payload.error || 'LLM unavailable', 'error', 'LLM key issue');
}

function showLlmBanner(message, hint) {
    let bar = document.getElementById('llmHealthBanner');
    if (!bar) {
        bar = document.createElement('div');
        bar.id = 'llmHealthBanner';
        bar.className = 'llm-banner';
        bar.setAttribute('role', 'alert');
        document.body.insertBefore(bar, document.body.firstChild);
    }
    bar.replaceChildren();
    bar.insertAdjacentHTML('beforeend', `
        <div class="llm-banner-body">
            <strong>${escapeHtml(message)}</strong>
            ${hint ? `<span class="llm-banner-hint">${escapeHtml(hint)}</span>` : ''}
            <a class="llm-banner-link" href="https://console.groq.com/keys" target="_blank" rel="noopener">
                Open Groq console →
            </a>
        </div>
        <button class="llm-banner-close" aria-label="Dismiss" type="button">×</button>
    `);
    bar.querySelector('.llm-banner-close').addEventListener('click', () => bar.remove());
    document.body.classList.add('has-llm-banner');
}

async function probeLlmHealth() {
    try {
        const res = await fetch('/api/llm/ping');
        if (!res.ok) return;
        const data = await res.json();
        if (!data.ok) {
            showLlmBanner(data.error || 'LLM key is invalid.', data.hint || '');
        } else {
            // Clean up any stale banner on a healthy ping.
            const bar = document.getElementById('llmHealthBanner');
            if (bar) bar.remove();
            document.body.classList.remove('has-llm-banner');
        }
    } catch (_) { /* silent */ }
}

document.addEventListener('DOMContentLoaded', () => {
    // Single probe at startup. Cheap, surfaces stale keys immediately.
    probeLlmHealth();
});

// =============================================================
// Phase 5 — Insights: run diff + recurring-failure grouping
// =============================================================

function populateDiffPickers() {
    const a = document.getElementById('diffA');
    const b = document.getElementById('diffB');
    if (!a || !b) return;
    const executed = (window.__sessions || []).filter(s => (s.state || '').toUpperCase() === 'EXECUTED');
    [a, b].forEach(sel => {
        sel.replaceChildren();
        sel.insertAdjacentHTML('beforeend', '<option value="">— select —</option>');
        executed.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.session_id;
            opt.textContent = `${s.feature || s.session_id.slice(0, 8)} · ${relativeTime(s.timestamp)}`;
            sel.appendChild(opt);
        });
    });
}

async function runDiff() {
    const a = document.getElementById('diffA').value;
    const b = document.getElementById('diffB').value;
    if (!a || !b) { toast('Pick two sessions first.', 'warn'); return; }
    if (a === b) { toast('Pick two different sessions.', 'warn'); return; }
    try {
        const res = await fetch(`/api/runs/diff?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        renderDiffRows(data.rows || []);
    } catch (err) {
        toast(err.message, 'error', 'Diff failed');
    }
}

function renderDiffRows(rows) {
    const tbody = document.getElementById('diffTbody');
    const wrap = document.getElementById('diffResult');
    const empty = document.getElementById('diffEmpty');
    tbody.replaceChildren();

    const order = { regressed: 0, new: 1, still_fail: 2, churn: 3, fixed: 4, removed: 5, stable: 6, new_pass: 7 };
    rows.sort((x, y) => (order[x.delta] || 9) - (order[y.delta] || 9));

    rows.forEach(r => {
        const tr = document.createElement('tr');
        const labels = {
            regressed: '↘️ regression', fixed: '↗️ fixed',
            still_fail: '⛔ still failing', new: '✨ new',
            removed: '🗑 removed', stable: '· no change', churn: '↔️ status churn',
        };
        const cls = {
            regressed: 'diff-delta-regress', fixed: 'diff-delta-fixed',
            still_fail: 'diff-delta-regress', new: 'diff-delta-new-fail',
            removed: 'diff-delta-stable', stable: 'diff-delta-stable',
            churn: 'diff-delta-stable',
        }[r.delta] || 'diff-delta-stable';
        tr.insertAdjacentHTML('beforeend', `
            <td><code>${escapeHtml(r.id)}</code></td>
            <td>${escapeHtml(r.description || '')}</td>
            <td>${escapeHtml(r.a_status || '—')}</td>
            <td>${escapeHtml(r.b_status || '—')}</td>
            <td class="${cls}">${labels[r.delta] || r.delta}</td>
        `);
        tbody.appendChild(tr);
    });

    wrap.classList.toggle('hidden', rows.length === 0);
    empty.classList.toggle('hidden', rows.length > 0);
}

// ---- Recurring failures: client-side grouping ----
function fingerprintError(err) {
    if (!err) return '';
    let s = String(err);
    // Strip variable bits: hex addresses, line numbers, ids, urls
    s = s.replace(/0x[0-9a-fA-F]+/g, '0x…');
    s = s.replace(/\bhttps?:\/\/[^\s'"]+/g, '<url>');
    s = s.replace(/(line\s+)\d+/gi, '$1<n>');
    s = s.replace(/[a-f0-9]{8,}/gi, '<hash>');
    s = s.replace(/\d{4,}/g, '<num>');
    // Truncate to first sentence for grouping stability
    const dot = s.indexOf(':');
    const cut = s.indexOf('\n');
    if (cut > 0 && cut < 120) s = s.slice(0, cut);
    if (dot > 0 && dot < 80) s = s.slice(0, dot + 60);
    return s.slice(0, 140).trim();
}

async function loadRecurringFailures() {
    try {
        const res = await fetch('/api/reports/global_insights');
        const data = await res.json();
        const cases = data.most_failing_tests || [];
        const groups = new Map();
        cases.forEach(c => {
            const key = fingerprintError(c.error || c.isolated_insight || c.description || '(no error)');
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(c);
        });
        const list = [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
        renderPatterns(list);
    } catch (err) {
        console.error('Recurring failures load failed:', err);
    }
}

function renderPatterns(groups) {
    const ul = document.getElementById('patternList');
    const empty = document.getElementById('patternEmpty');
    if (!ul) return;
    ul.replaceChildren();
    if (!groups.length) {
        empty.classList.remove('hidden');
        return;
    }
    empty.classList.add('hidden');
    groups.slice(0, 12).forEach(([fp, cases]) => {
        const li = document.createElement('li');
        li.className = 'pattern-row';
        const ids = cases.map(c => c.test_id || c.id).filter(Boolean).slice(0, 4).join(', ');
        li.insertAdjacentHTML('beforeend', `
            <span class="pattern-count">${cases.length}</span>
            <span class="pattern-text" title="${escapeHtml(fp)}">${escapeHtml(fp || '(no error message)')}</span>
            <span class="pattern-cases">${escapeHtml(ids || '')}</span>
        `);
        ul.appendChild(li);
    });
}

function refreshInsightsPanels() {
    populateDiffPickers();
    loadRecurringFailures();
}

// Hook into existing nav: when Insights tab is activated, refresh panels.
document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('diffRunBtn');
    if (btn) btn.addEventListener('click', runDiff);
    const insightsTab = document.getElementById('tab-globalStatsView');
    if (insightsTab) insightsTab.addEventListener('click', refreshInsightsPanels);
});

// =============================================================
// Phase 5 — Markdown export button on session header
// =============================================================
function updateExportButton() {
    let host = document.getElementById('sessionExportHost');
    const title = document.getElementById('activeSessionTitle');
    if (!title) return;
    if (!host) {
        // Wrap the existing title in a header-row + actions slot.
        const wrap = document.createElement('div');
        wrap.className = 'session-header-row';
        title.parentNode.insertBefore(wrap, title);
        wrap.appendChild(title);
        host = document.createElement('div');
        host.id = 'sessionExportHost';
        host.className = 'session-actions';
        wrap.appendChild(host);
    }
    host.replaceChildren();
    if (currentSessionId) {
        const a = document.createElement('a');
        a.className = 'export-btn';
        a.href = `/api/sessions/${currentSessionId}/export.md`;
        a.setAttribute('download', '');
        a.textContent = '⬇ Export .md';
        host.appendChild(a);

        // Feature #1 — export as runnable test code (Playwright/Selenium/Cypress)
        const codeWrap = document.createElement('div');
        codeWrap.className = 'code-export';
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'export-btn';
        btn.textContent = '⬇ Export code ▾';
        const menu = document.createElement('div');
        menu.className = 'code-export-menu hidden';
        const frameworks = [
            ['playwright', 'Playwright (Python)'],
            ['selenium', 'Selenium + pytest'],
            ['cypress', 'Cypress (JS)'],
        ];
        frameworks.forEach(([fw, label]) => {
            const link = document.createElement('a');
            link.href = `/api/sessions/${currentSessionId}/export.code?framework=${fw}`;
            link.setAttribute('download', '');
            link.textContent = label;
            link.addEventListener('click', () => menu.classList.add('hidden'));
            menu.appendChild(link);
        });
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            menu.classList.toggle('hidden');
        });
        document.addEventListener('click', () => menu.classList.add('hidden'));
        codeWrap.appendChild(btn);
        codeWrap.appendChild(menu);
        host.appendChild(codeWrap);
    }
}

// Patch loadSessionData/generateBtn flow lightly by refreshing on activeSessionState reveal.
new MutationObserver(updateExportButton).observe(
    document.getElementById('activeSessionState'),
    { attributes: true, attributeFilter: ['class'] },
);

// =============================================================
// Feature #12 — "Why did this fail?" deep-dive modal
// =============================================================
function openDeepDive(caseId) {
    if (!currentSessionId) return;
    const tc = findCase(caseId);
    if (!tc) return;

    const modal = document.getElementById('deepDiveModal');
    document.getElementById('deepDiveTitle').innerText = `Why did ${caseId} fail?`;
    document.getElementById('deepDiveLoading').classList.remove('hidden');
    document.getElementById('deepDiveContent').classList.add('hidden');
    document.getElementById('deepDiveConfidence').textContent = '';
    modal.classList.remove('hidden');

    fetch(`/api/cases/${currentSessionId}/${caseId}/deep_dive`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    }).then(r => r.json()).then(data => {
        if (data.error) throw new Error(data.error);
        renderDeepDive(data);
    }).catch(err => {
        document.getElementById('deepDiveLoading').innerText =
            'Deep-dive unavailable: ' + err.message;
    });
}

function renderDeepDive(data) {
    const rep = data.report || {};
    document.getElementById('deepDiveLoading').classList.add('hidden');
    document.getElementById('deepDiveContent').classList.remove('hidden');

    // Confidence pill
    const conf = (rep.confidence || 'low').toLowerCase();
    const cEl = document.getElementById('deepDiveConfidence');
    cEl.className = 'dd-confidence dd-conf-' + conf;
    cEl.textContent = conf + ' confidence';

    document.getElementById('ddSummary').textContent = rep.summary || '(none)';
    document.getElementById('ddRoot').textContent = rep.root_cause || '(none)';
    document.getElementById('ddWhy').textContent = rep.why_now || '(none)';
    document.getElementById('ddPattern').textContent = rep.pattern || '(none)';
    document.getElementById('ddFix').textContent = rep.suggested_fix || '(none)';

    const patch = rep.suggested_action_plan_patch;
    const patchWrap = document.getElementById('ddPatchWrap');
    const patchEl = document.getElementById('ddPatch');
    if (patch && typeof patch === 'object') {
        patchEl.textContent = JSON.stringify(patch, null, 2);
        patchWrap.classList.remove('hidden');
    } else {
        patchWrap.classList.add('hidden');
    }

    const ctx = data.context_used || {};
    document.getElementById('ddContextMeta').textContent =
        `Used ${ctx.console_log_count || 0} console log(s), ` +
        `${ctx.prior_run_count || 0} prior failure(s), ` +
        `${ctx.locator_cache_count || 0} locator-cache hint(s).`;
}

function closeDeepDive() {
    document.getElementById('deepDiveModal').classList.add('hidden');
}

document.addEventListener('DOMContentLoaded', () => {
    const modal = document.getElementById('deepDiveModal');
    if (!modal) return;
    modal.querySelector('.modal-close').addEventListener('click', closeDeepDive);
    document.getElementById('ddCloseBtn').addEventListener('click', closeDeepDive);
    modal.addEventListener('click', e => { if (e.target === modal) closeDeepDive(); });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) closeDeepDive();
    });
});


// =============================================================
// Feature #11 — Create ticket modal
// =============================================================
let __ticketTargetCase = null;

function openCreateTicket(caseId) {
    const modal = document.getElementById('ticketModal');
    if (!modal) return;
    __ticketTargetCase = caseId;
    document.getElementById('ticketModalTitle').textContent = 'Create a ticket for ' + caseId;
    document.getElementById('ticketProjectOverride').value = '';
    document.getElementById('ticketTitleOverride').value = '';
    document.getElementById('ticketStatus').textContent = '';
    document.getElementById('ticketResult').classList.add('hidden');
    document.getElementById('ticketSubmitBtn').disabled = false;

    // Reflect available providers — disable radios when no creds
    const map = window.__ticketProviders || {};
    const jiraRadio = document.getElementById('ticketProviderJira');
    const linearRadio = document.getElementById('ticketProviderLinear');
    if (jiraRadio) jiraRadio.disabled = !map.jira;
    if (linearRadio) linearRadio.disabled = !map.linear;
    if (jiraRadio && map.jira) jiraRadio.checked = true;
    else if (linearRadio && map.linear) linearRadio.checked = true;

    const hasAny = map.jira || map.linear;
    document.getElementById('ticketModalConfigMissing').classList.toggle('hidden', !!hasAny);
    document.getElementById('ticketModalForm').classList.toggle('hidden', !hasAny);

    modal.classList.remove('hidden');
}

function closeCreateTicket() {
    const modal = document.getElementById('ticketModal');
    if (modal) modal.classList.add('hidden');
    __ticketTargetCase = null;
}

async function submitCreateTicket() {
    if (!__ticketTargetCase || !currentSessionId) return;
    const provider = (document.querySelector('input[name="ticketProvider"]:checked') || {}).value;
    if (!provider) {
        toast('Pick a provider first.', 'warn');
        return;
    }
    const btn = document.getElementById('ticketSubmitBtn');
    const status = document.getElementById('ticketStatus');
    btn.disabled = true;
    status.textContent = 'Creating ticket…';
    status.className = 'ticket-status';

    try {
        const res = await fetch(`/api/cases/${currentSessionId}/${__ticketTargetCase}/create_ticket`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                provider: provider,
                project_or_team: document.getElementById('ticketProjectOverride').value.trim() || null,
                summary_override: document.getElementById('ticketTitleOverride').value.trim() || null,
                include_deep_dive: document.getElementById('ticketIncludeDeepDive').checked,
            }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
        status.textContent = `Created ${data.key || ''} on ${data.provider.toUpperCase()}.`;
        status.className = 'ticket-status is-ok';
        const a = document.getElementById('ticketResultLink');
        a.href = data.url || '#';
        a.textContent = data.url || data.key || 'Open ticket';
        document.getElementById('ticketResult').classList.remove('hidden');
        toast(`Filed ${data.key}`, 'success', 'Ticket created');
    } catch (e) {
        status.textContent = e.message;
        status.className = 'ticket-status is-err';
        toast(e.message, 'error', 'Ticket failed');
    } finally {
        btn.disabled = false;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const modal = document.getElementById('ticketModal');
    if (!modal) return;
    modal.querySelector('.modal-close').addEventListener('click', closeCreateTicket);
    document.getElementById('ticketCancelBtn').addEventListener('click', closeCreateTicket);
    document.getElementById('ticketSubmitBtn').addEventListener('click', submitCreateTicket);
    modal.addEventListener('click', (e) => { if (e.target === modal) closeCreateTicket(); });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) closeCreateTicket();
    });
    const goSettings = document.getElementById('ticketGoToSettings');
    if (goSettings) goSettings.addEventListener('click', (e) => {
        e.preventDefault();
        closeCreateTicket();
        const tab = document.getElementById('tab-settingsView');
        if (tab) tab.click();
    });
});


// =============================================================
// Feature #6 — Screenshot → tests (vision LLM)
// =============================================================
let __screenshotB64 = null;
let __screenshotMime = "image/png";

function openScreenshotModal() {
    const modal = document.getElementById('screenshotModal');
    if (!modal) return;
    __screenshotB64 = null;
    __screenshotMime = "image/png";
    document.getElementById('screenshotPreview').classList.add('hidden');
    document.getElementById('screenshotPreview').src = '';
    document.getElementById('screenshotPlaceholder').classList.remove('hidden');
    document.getElementById('screenshotHint').value = '';
    document.getElementById('screenshotCount').value = '5';
    document.getElementById('screenshotStatus').textContent = '';
    document.getElementById('screenshotSubmitBtn').disabled = true;
    modal.classList.remove('hidden');
}

function closeScreenshotModal() {
    const modal = document.getElementById('screenshotModal');
    if (modal) modal.classList.add('hidden');
}

function _loadImageFile(file) {
    if (!file) return;
    if (!file.type || !['image/png','image/jpeg','image/webp'].includes(file.type)) {
        toast('Use PNG, JPEG, or WebP.', 'warn', 'Unsupported image');
        return;
    }
    if (file.size > 6 * 1024 * 1024) {
        toast('Image is over 6 MB. Compress it first.', 'warn', 'Too large');
        return;
    }
    const reader = new FileReader();
    reader.onload = e => {
        const result = e.target.result || '';
        // result is "data:image/png;base64,...."
        const commaIdx = result.indexOf(',');
        __screenshotB64 = commaIdx >= 0 ? result.slice(commaIdx + 1) : '';
        __screenshotMime = file.type;
        const img = document.getElementById('screenshotPreview');
        img.src = result;
        img.classList.remove('hidden');
        document.getElementById('screenshotPlaceholder').classList.add('hidden');
        document.getElementById('screenshotSubmitBtn').disabled = !__screenshotB64;
    };
    reader.readAsDataURL(file);
}

async function submitScreenshotGeneration() {
    if (!__screenshotB64) {
        toast('Add a screenshot first.', 'warn');
        return;
    }
    const btn = document.getElementById('screenshotSubmitBtn');
    const status = document.getElementById('screenshotStatus');
    btn.disabled = true;
    status.textContent = 'Asking the vision model to read the screenshot…';
    status.className = 'ticket-status';

    const payload = {
        image_b64: __screenshotB64,
        mime_type: __screenshotMime,
        hint: document.getElementById('screenshotHint').value.trim() || null,
        count: parseInt(document.getElementById('screenshotCount').value, 10) || 5,
    };
    try {
        const res = await fetch('/api/smart_input_image', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (res.status === 401 && data.code === 'llm_unavailable') {
            handleLlmConfigError(data);
            throw new Error(data.error || 'LLM unavailable');
        }
        if (res.status === 409) {
            toast(data.error || 'Quota full.', 'warn', 'Session limit');
            throw new Error(data.error || 'Quota');
        }
        if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));

        status.textContent = `Generated ${data.session.test_cases.length} cases.`;
        status.className = 'ticket-status is-ok';

        // Drop the user straight into the active session view.
        closeScreenshotModal();
        welcomeState.classList.add('hidden');
        activeSessionState.classList.remove('hidden');
        activeSessionTitle.innerText = data.session.feature;
        activeSessionStatus.innerText = data.session.state;
        currentSessionId = data.session.session_id;
        renderTestCases(data.session.test_cases, testCasesContainer);
        automationPrompt.classList.remove('hidden');
        loadSessions();
        loadGlobalInsights();
        toast('Tests built from screenshot.', 'success', 'Vision generation');
    } catch (e) {
        status.textContent = e.message;
        status.className = 'ticket-status is-err';
    } finally {
        btn.disabled = !__screenshotB64;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const chip = document.getElementById('screenshotChip');
    const modal = document.getElementById('screenshotModal');
    if (!chip || !modal) return;
    chip.addEventListener('click', openScreenshotModal);

    const dropzone = document.getElementById('screenshotDropZone');
    const fileInput = document.getElementById('screenshotFileInput');

    dropzone.addEventListener('click', () => fileInput.click());
    dropzone.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
    });

    fileInput.addEventListener('change', () => {
        const f = fileInput.files && fileInput.files[0];
        if (f) _loadImageFile(f);
    });

    ['dragover','dragenter'].forEach(ev => dropzone.addEventListener(ev, (e) => {
        e.preventDefault();
        dropzone.classList.add('is-dragover');
    }));
    ['dragleave','drop'].forEach(ev => dropzone.addEventListener(ev, (e) => {
        e.preventDefault();
        dropzone.classList.remove('is-dragover');
    }));
    dropzone.addEventListener('drop', (e) => {
        const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if (f) _loadImageFile(f);
    });

    // Paste from clipboard while the modal is open
    document.addEventListener('paste', (e) => {
        if (modal.classList.contains('hidden')) return;
        const items = e.clipboardData && e.clipboardData.items;
        if (!items) return;
        for (const it of items) {
            if (it.type && it.type.startsWith('image/')) {
                const f = it.getAsFile();
                if (f) { _loadImageFile(f); break; }
            }
        }
    });

    modal.querySelector('.modal-close').addEventListener('click', closeScreenshotModal);
    document.getElementById('screenshotCancelBtn').addEventListener('click', closeScreenshotModal);
    document.getElementById('screenshotSubmitBtn').addEventListener('click', submitScreenshotGeneration);
    modal.addEventListener('click', (e) => { if (e.target === modal) closeScreenshotModal(); });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) closeScreenshotModal();
    });
});

// =============================================================
// Feature #10 — Import recording (.abhimate.json from Chrome ext)
// =============================================================
async function importRecordingJson(jsonText) {
    let payload;
    try {
        payload = JSON.parse(jsonText);
    } catch (e) {
        toast('That file isn\'t valid JSON: ' + e.message, 'error');
        return;
    }
    try {
        const res = await fetch('/api/import/recording', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: jsonText,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const msg = data.error || ('HTTP ' + res.status);
            toast('Import failed: ' + msg, 'error');
            return;
        }
        toast(
            `Imported "${data.feature}" (${data.imported?.action_count || 0} actions)`,
            'success', 'Recording'
        );
        // Refresh the session list + load the new session.
        if (typeof loadSessions === 'function') await loadSessions();
        if (typeof loadSessionData === 'function' && data.session_id) {
            loadSessionData(data.session_id);
        }
    } catch (e) {
        toast('Import failed: ' + e.message, 'error');
    }
}

function _readFileAsText(file) {
    return new Promise((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(r.result || '');
        r.onerror = () => reject(r.error || new Error('read failed'));
        r.readAsText(file);
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const chip = document.getElementById('recordingChip');
    const fileInput = document.getElementById('recordingFileInput');
    if (!chip || !fileInput) return;
    chip.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', async () => {
        const f = fileInput.files && fileInput.files[0];
        if (!f) return;
        try {
            const text = await _readFileAsText(f);
            await importRecordingJson(text);
        } finally {
            fileInput.value = '';     // allow re-importing the same file
        }
    });

    // Drag-drop a .json onto the featureInput textarea to import it.
    const drop = document.getElementById('featureInput');
    if (drop) {
        ['dragover','dragenter'].forEach(ev => drop.addEventListener(ev, (e) => {
            if (e.dataTransfer && Array.from(e.dataTransfer.items || []).some(i => i.kind === 'file')) {
                e.preventDefault();
                drop.classList.add('is-dragover');
            }
        }));
        ['dragleave','drop'].forEach(ev => drop.addEventListener(ev, (e) => {
            drop.classList.remove('is-dragover');
        }));
        drop.addEventListener('drop', async (e) => {
            const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
            if (!f) return;
            if (!/\.json$/i.test(f.name) && f.type !== 'application/json') return;
            e.preventDefault();
            const text = await _readFileAsText(f);
            await importRecordingJson(text);
        });
    }
});
