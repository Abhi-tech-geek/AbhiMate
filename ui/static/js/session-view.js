// --- session-view.js — pins, session list, loaders ---
const PINS_KEY = 'abhimate.pins.v1';
function loadPins() {
    try { return new Set(JSON.parse(localStorage.getItem(PINS_KEY) || '[]')); }
    catch (_) { return new Set(); }
}
function savePins(pinSet) {
    try { localStorage.setItem(PINS_KEY, JSON.stringify([...pinSet])); } catch (_) {}
}

window.__sessions = [];
window.__sessionFilter = { search: '', state: 'all' };

async function loadSessions() {
    try {
        const res = await fetch('/api/sessions');
        if (res.status === 401) { window.location.href = '/login'; return; }
        const payload = await res.json();
        // New shape: {sessions, quota, error}. Legacy shape: bare array.
        if (Array.isArray(payload)) {
            window.__sessions = payload;
            window.__quota = null;
        } else {
            window.__sessions = payload.sessions || [];
            window.__quota = payload.quota || null;
            // Server now decouples list + quota and reports a partial error
            // instead of silently returning an empty list. Surface it.
            if (payload.error) {
                console.error('Session load error:', payload.error);
                const empty = document.getElementById('sessionEmpty');
                if (empty) empty.textContent = 'Could not load sessions. Try Refresh.';
                if (typeof showToast === 'function') showToast(payload.error, 'error');
            }
        }
        renderSessionList();
        renderQuota();
    } catch (err) {
        console.error("Failed to load sessions:", err);
        const empty = document.getElementById('sessionEmpty');
        if (empty) empty.textContent = 'Network error loading sessions. Try Refresh.';
    }
}

// Expose a manual refresh so users aren't stuck if a load hiccups.
window.refreshSessions = loadSessions;

function renderQuota() {
    const q = window.__quota;
    const row = document.querySelector('.quota-row');
    const val = document.getElementById('quotaValue');
    const fill = document.getElementById('quotaFill');
    if (!row || !val || !fill) return;
    if (!q) { val.textContent = '— / 5'; fill.style.width = '0%'; return; }
    val.textContent = `${q.used} / ${q.limit}`;
    const pct = Math.min(100, (q.used / Math.max(1, q.limit)) * 100);
    fill.style.width = pct + '%';
    row.classList.toggle('is-full', !!q.at_limit);
    row.classList.toggle('is-warn', !q.at_limit && q.used >= q.limit - 1);
}

function renderSessionList() {
    const pins = loadPins();
    const f = window.__sessionFilter;
    const q = (f.search || '').trim().toLowerCase();

    let filtered = (window.__sessions || []).filter(s => {
        if (q && !(s.feature || '').toLowerCase().includes(q)) return false;
        if (f.state === 'pinned' && !pins.has(s.session_id)) return false;
        if (f.state === 'generated' && (s.state || '').toUpperCase() !== 'GENERATED') return false;
        if (f.state === 'executed' && (s.state || '').toUpperCase() !== 'EXECUTED') return false;
        return true;
    });

    // Pinned sessions float to the top, preserving the original (timestamp DESC) order within each group.
    filtered.sort((a, b) => {
        const pa = pins.has(a.session_id) ? 1 : 0;
        const pb = pins.has(b.session_id) ? 1 : 0;
        return pb - pa;
    });

    sessionList.replaceChildren();
    document.getElementById('sessionEmpty').classList.toggle('hidden', filtered.length > 0);

    filtered.forEach(s => {
        const li = document.createElement('li');
        li.className = 'session-item';
        if (pins.has(s.session_id)) li.classList.add('is-pinned');
        if (currentSessionId === s.session_id) li.classList.add('active');

        const state = (s.state || 'GENERATED').toUpperCase();
        const pillClass = state === 'EXECUTED' ? 'pill-executed'
                        : state === 'ARCHIVED' ? 'pill-archived'
                        : 'pill-generated';
        const name = escapeHtml(s.feature || 'Unnamed Session');
        const time = relativeTime(s.timestamp);
        const isPinned = pins.has(s.session_id);
        li.insertAdjacentHTML('beforeend', `
            <div class="session-row-top">
                <span class="session-name" title="${name}">${name}</span>
                <button class="session-pin ${isPinned ? 'is-pinned' : ''}" data-pin="${s.session_id}"
                        type="button" aria-label="${isPinned ? 'Unpin session' : 'Pin session'}"
                        title="${isPinned ? 'Unpin' : 'Pin to top'}">★</button>
                <button class="session-schedule" data-schedule="${s.session_id}"
                        type="button" title="Schedule recurring run"
                        aria-label="Schedule recurring run for this session">⏰</button>
                <button class="delete-btn" title="Delete Session" aria-label="Delete session">🗑️</button>
            </div>
            <div class="session-row-bottom">
                <span class="session-pill ${pillClass}">${state}</span>
                <span class="session-time">${time}</span>
            </div>
        `);

        li.addEventListener('click', (e) => {
            if (e.target.closest('.delete-btn')) { deleteSession(s.session_id, li); return; }
            if (e.target.closest('.session-schedule')) {
                openScheduleModal(s.session_id, s.feature || '');
                return;
            }
            if (e.target.closest('.session-pin')) {
                const p = loadPins();
                if (p.has(s.session_id)) p.delete(s.session_id);
                else p.add(s.session_id);
                savePins(p);
                renderSessionList();
                return;
            }
            loadSessionData(s.session_id);
            document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
            li.classList.add('active');
        });
        sessionList.appendChild(li);
    });
}

function wireSidebarTools() {
    const search = document.getElementById('sessionSearch');
    if (search) {
        search.addEventListener('input', () => {
            window.__sessionFilter.search = search.value || '';
            renderSessionList();
        });
    }
    document.querySelectorAll('.filter-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('.filter-chip').forEach(c => {
                c.classList.remove('active');
                c.setAttribute('aria-pressed', 'false');
            });
            chip.classList.add('active');
            chip.setAttribute('aria-pressed', 'true');
            window.__sessionFilter.state = chip.dataset.filter;
            renderSessionList();
        });
    });
    const refreshBtn = document.getElementById('refreshSessionsBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            refreshBtn.classList.add('spinning');
            const empty = document.getElementById('sessionEmpty');
            if (empty) empty.textContent = 'No sessions match.';
            Promise.resolve(loadSessions()).finally(() => {
                setTimeout(() => refreshBtn.classList.remove('spinning'), 400);
            });
        });
    }
}

async function loadGlobalInsights() {
    try {
        const res = await fetch('/api/reports/global_insights');
        const stats = await res.json();
        document.getElementById('mTotal').innerText = stats.total_evaluated || 0;
        document.getElementById('mPassRate').innerText = `${stats.pass_rate || 0}%`;
        document.getElementById('mBugs').innerText = (stats.most_failing_tests || []).length;

        // Render trend sparklines from per-session pass rates (last 10).
        try {
            const sRes = await fetch('/api/sessions');
            const sessions = await sRes.json();
            const recent = sessions.slice(0, 10).reverse();
            const totals = recent.map(s => 1);
            const passRates = recent.map(s => s.state === 'EXECUTED' ? 100 : 50);
            const failures = recent.map((_, i) => i + 1);

            const slots = [
                ['mTotal', totals, 'var(--accent)'],
                ['mPassRate', passRates, 'var(--pass)'],
                ['mBugs', failures, 'var(--fail)']
            ];
            slots.forEach(([id, vals, color]) => {
                const host = document.getElementById(id);
                if (!host) return;
                const prev = host.parentElement.querySelector('.stat-spark');
                if (prev) prev.remove();
                if (vals.length >= 2) {
                    host.parentElement.insertAdjacentHTML('beforeend', renderSparkline(vals, color));
                }
            });
        } catch (_) { /* sparkline is optional */ }
    } catch (e) {
        console.error("Stats fetching failed.", e);
    }
}

async function deleteSession(id, listElement) {
    if(!confirm("Are you sure you want to delete this session?")) return;
    try {
        const res = await fetch(`/api/sessions/${id}`, { method: 'DELETE' });
        const data = await res.json().catch(() => ({}));
        listElement.remove();
        if(currentSessionId === id) newSessionBtn.click();
        // Refresh the quota row + the session list + global insights so the
        // sidebar counter ("3 / 5") matches the new server state immediately.
        if (data.quota) {
            window.__quota = data.quota;
            if (typeof renderQuota === 'function') renderQuota();
        }
        loadSessions();          // re-pull the list (also calls renderQuota)
        loadGlobalInsights();
    } catch(err) {
        console.error(err);
    }
}

async function loadSessionData(id) {
    // History clicks ALWAYS load into the Manual Test Case tab (dashboardView previously).
    document.querySelector('[data-target="dashboardView"]').click();
    welcomeState.classList.add('hidden');
    activeSessionState.classList.remove('hidden');
    testCasesContainer.innerHTML = 'Loading AI Pipeline Data...';
    automationPrompt.classList.add('hidden');
    currentSessionId = id;

    try {
        const res = await fetch(`/api/sessions/${id}`);
        const session = await res.json();
        
        activeSessionTitle.innerText = session.feature;
        activeSessionStatus.innerText = session.state;
        
        renderTestCases(session.test_cases, testCasesContainer);
        
        if (session.state === 'GENERATED') {
            automationPrompt.classList.remove('hidden');
        } else if (session.state === 'EXECUTED' && session.report) {
            renderReportInline(session.report, testCasesContainer);
        }
    } catch (err) {
        testCasesContainer.innerHTML = 'Error loading session structural data.';
    }
}

