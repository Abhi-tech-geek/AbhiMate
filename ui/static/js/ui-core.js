// --- ui-core.js — utilities + theme + settings + tabs + sidebar tools ---
document.addEventListener('DOMContentLoaded', () => {
    loadSessions();
    loadGlobalInsights();
    wireExampleChips();
    wireLightbox();
    wireThemeToggle();
    wireSettings();
    wireSidebarTools();
});

// ---- Toast notifications ----
function toast(message, variant, title) {
    variant = variant || 'info';
    const host = document.getElementById('toastStack');
    if (!host) { console.log(`[${variant}] ${title || ''} ${message}`); return; }
    const el = document.createElement('div');
    el.className = 'toast toast-' + variant;
    el.setAttribute('role', variant === 'error' ? 'alert' : 'status');
    el.insertAdjacentHTML('beforeend', `
        <div class="toast-body">
            ${title ? `<div class="toast-title">${escapeHtml(title)}</div>` : ''}
            <div>${escapeHtml(message)}</div>
        </div>
        <button class="toast-dismiss" aria-label="Dismiss notification" type="button">×</button>
    `);
    const dismiss = () => {
        el.classList.add('toast-out');
        setTimeout(() => el.remove(), 200);
    };
    el.querySelector('.toast-dismiss').addEventListener('click', dismiss);
    host.appendChild(el);
    setTimeout(dismiss, 4500);
}

function currentTheme() {
    return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem('abhimate.theme', theme); } catch (_) {}
    const btn = document.getElementById('themeToggle');
    if (btn) {
        btn.setAttribute('aria-label',
            theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme');
    }
    const settingsToggle = document.getElementById('themeToggleSettings');
    if (settingsToggle) settingsToggle.checked = (theme === 'light');
}

function wireThemeToggle() {
    const btn = document.getElementById('themeToggle');
    if (btn) {
        applyTheme(currentTheme());
        btn.addEventListener('click', () =>
            applyTheme(currentTheme() === 'light' ? 'dark' : 'light'));
    }
    const settingsToggle = document.getElementById('themeToggleSettings');
    if (settingsToggle) {
        settingsToggle.checked = (currentTheme() === 'light');
        settingsToggle.addEventListener('change', () =>
            applyTheme(settingsToggle.checked ? 'light' : 'dark'));
    }
}

// ---- Settings persistence ----
const SETTINGS_KEY = 'abhimate.settings.v1';

function loadSettings() {
    try {
        const raw = localStorage.getItem(SETTINGS_KEY);
        return raw ? JSON.parse(raw) : {};
    } catch (_) { return {}; }
}

function saveSettings(patch) {
    try {
        const cur = loadSettings();
        const next = Object.assign({}, cur, patch);
        localStorage.setItem(SETTINGS_KEY, JSON.stringify(next));
    } catch (_) {}
}

function updateModelBadge(value) {
    const badge = document.getElementById('navModelBadge');
    if (!badge) return;
    badge.textContent = value === 'fast' ? '8B' : '70B';
    badge.title = value === 'fast' ? 'Fast model (Llama 3.1 8B)' : 'Accurate model (Llama 3.3 70B)';
}

function wireSettings() {
    const persisted = loadSettings();
    const fields = ['modelSelect', 'langSelect', 'envSelect', 'caseCountSelect', 'defaultCountInput', 'headlessToggle', 'deviceSelect'];
    fields.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        if (persisted[id] !== undefined) {
            if (el.type === 'checkbox') el.checked = !!persisted[id];
            else el.value = persisted[id];
        }
        el.addEventListener('change', () => {
            const val = el.type === 'checkbox' ? el.checked : el.value;
            saveSettings({ [id]: val });
            if (id === 'modelSelect') updateModelBadge(el.value);
            if (id === 'defaultCountInput') {
                const cnt = document.getElementById('caseCountSelect');
                if (cnt && [...cnt.options].some(o => o.value === String(el.value))) {
                    cnt.value = String(el.value);
                    saveSettings({ caseCountSelect: cnt.value });
                }
            }
            if (id === 'caseCountSelect') {
                const di = document.getElementById('defaultCountInput');
                if (di) { di.value = el.value; saveSettings({ defaultCountInput: el.value }); }
            }
        });
    });
    const ms = document.getElementById('modelSelect');
    if (ms) updateModelBadge(ms.value);
}

// -------------------------------------------------------------
// Phase 2 helpers
// -------------------------------------------------------------
function relativeTime(epochSeconds) {
    if (!epochSeconds) return '';
    const diff = Date.now() / 1000 - epochSeconds;
    if (diff < 60) return Math.floor(diff) + 's ago';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
    return new Date(epochSeconds * 1000).toLocaleDateString();
}

function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function wireExampleChips() {
    document.querySelectorAll('.example-chips .chip').forEach(chip => {
        chip.addEventListener('click', () => {
            featureInput.value = chip.dataset.prompt || '';
            featureInput.focus();
        });
    });
}

function wireLightbox() {
    const lb = document.getElementById('lightbox');
    const img = document.getElementById('lightboxImg');
    const close = () => { lb.classList.add('hidden'); img.src = ''; };
    lb.addEventListener('click', e => {
        if (e.target === lb || e.target.classList.contains('lightbox-close')) close();
    });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && !lb.classList.contains('hidden')) close();
    });
}

function openLightbox(src) {
    const lb = document.getElementById('lightbox');
    document.getElementById('lightboxImg').src = src;
    lb.classList.remove('hidden');
}

function showSkeletonCards(container, n) {
    n = n || 3;
    container.replaceChildren();
    const tpl = `<div class="skeleton-card"><div class="skeleton-line h-20 w-30"></div><div class="skeleton-line w-80"></div><div class="skeleton-line w-60"></div><div class="skeleton-line w-100"></div><div class="skeleton-line w-80"></div></div>`;
    for (let i = 0; i < n; i++) container.insertAdjacentHTML('beforeend', tpl);
}

function renderSparkline(values, color) {
    if (!values || values.length < 2) return '';
    const w = 100, h = 30;
    const min = Math.min(...values), max = Math.max(...values);
    const range = max - min || 1;
    const step = w / (values.length - 1);
    const points = values.map((v, i) =>
        (i * step).toFixed(1) + ',' + (h - ((v - min) / range) * (h - 4) - 2).toFixed(1)
    ).join(' L ');
    return '<svg class="stat-spark" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
           '<path d="M ' + points + '" style="stroke:' + (color || 'var(--accent)') + '"/></svg>';
}

// Navigation Logic — click + arrow-key navigation per WAI-ARIA tablist pattern.
function activateTab(tab) {
    navTabs.forEach(t => {
        const isMe = t === tab;
        t.classList.toggle('active', isMe);
        t.setAttribute('aria-selected', isMe ? 'true' : 'false');
        t.setAttribute('tabindex', isMe ? '0' : '-1');
    });
    viewPanels.forEach(p => {
        const show = p.id === tab.dataset.target;
        p.classList.toggle('active-view', show);
        if (show) p.removeAttribute('hidden'); else p.setAttribute('hidden', '');
    });
    if (tab.dataset.target === 'globalStatsView') {
        loadGlobalInsights();
    }
}

navTabs.forEach((tab, idx) => {
    tab.addEventListener('click', () => activateTab(tab));
    tab.addEventListener('keydown', (e) => {
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft' &&
            e.key !== 'Home' && e.key !== 'End') return;
        e.preventDefault();
        let nextIdx;
        if (e.key === 'ArrowRight') nextIdx = (idx + 1) % navTabs.length;
        else if (e.key === 'ArrowLeft') nextIdx = (idx - 1 + navTabs.length) % navTabs.length;
        else if (e.key === 'Home') nextIdx = 0;
        else nextIdx = navTabs.length - 1;
        activateTab(navTabs[nextIdx]);
        navTabs[nextIdx].focus();
    });
});

navToReportsBtn.addEventListener('click', () => {
    navTabs.forEach(t => t.classList.remove('active'));
    viewPanels.forEach(p => p.classList.remove('active-view'));
    document.getElementById('reportsView').classList.add('active-view');
    initReportsDashboard();
});

sidebarToggle.addEventListener('click', () => {
    mainSidebar.classList.toggle('collapsed');
    const collapsed = mainSidebar.classList.contains('collapsed');
    sidebarToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
});

// Session Management
newSessionBtn.addEventListener('click', () => {
    currentSessionId = null;
    featureInput.value = '';
    
    // Clear Manual View Context
    welcomeState.classList.remove('hidden');
    activeSessionState.classList.add('hidden');
    testCasesContainer.innerHTML = '';
    activeSessionTitle.innerText = '...';
    activeSessionStatus.innerText = '';
    automationPrompt.classList.add('hidden');
    
    // Clear Automation View Context
    automationResultsContainer.innerHTML = '';
    automationResultsContainer.classList.add('hidden');
    
    document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
});


// =============================================================
// Phase 5 — Command palette (Cmd/Ctrl + K)
// =============================================================
var __cmdActiveIdx = 0;
var __cmdItems = [];

function openCmdPalette() {
    const back = document.getElementById('cmdPalette');
    if (!back) return;
    back.classList.remove('hidden');
    back.setAttribute('aria-hidden', 'false');
    const input = document.getElementById('cmdInput');
    input.value = '';
    renderCmdResults('');
    setTimeout(() => input.focus(), 0);
}

function closeCmdPalette() {
    const back = document.getElementById('cmdPalette');
    if (!back) return;
    back.classList.add('hidden');
    back.setAttribute('aria-hidden', 'true');
}

function buildCmdItems(query) {
    const q = (query || '').toLowerCase().trim();
    const items = [];

    // Nav actions
    const navActions = [
        { kind: 'Nav',     label: 'Go to Tests',     hint: 'Switch to the Tests tab', run: () => clickTab('tab-dashboardView') },
        { kind: 'Nav',     label: 'Go to Runs',      hint: 'Switch to the Runs tab',  run: () => clickTab('tab-automatedView') },
        { kind: 'Nav',     label: 'Go to Insights',  hint: 'Switch to the Insights tab', run: () => clickTab('tab-globalStatsView') },
        { kind: 'Nav',     label: 'Go to Settings',  hint: 'Switch to the Settings tab', run: () => clickTab('tab-settingsView') },
        { kind: 'Nav',     label: 'Open Reports',    hint: 'View per-session reports',   run: () => { const b = document.getElementById('navToReportsBtn'); if (b) b.click(); } },
        { kind: 'Action',  label: 'New session',     hint: 'Clear the current workspace', run: () => { const b = document.getElementById('newSessionBtn'); if (b) b.click(); } },
        { kind: 'Action',  label: 'Toggle theme',    hint: 'Light ⇄ Dark',
          run: () => applyTheme(currentTheme() === 'light' ? 'dark' : 'light') },
        { kind: 'Action',  label: 'Focus prompt',    hint: 'Jump to the feature prompt',
          run: () => { const el = document.getElementById('featureInput'); if (el) { clickTab('tab-dashboardView'); el.focus(); } } },
    ];
    items.push(...navActions);

    // Sessions (search by name)
    (window.__sessions || []).slice(0, 50).forEach(s => {
        items.push({
            kind: 'Session',
            label: s.feature || '(unnamed)',
            hint: (s.state || '').toLowerCase() + ' · ' + relativeTime(s.timestamp),
            run: () => { if (typeof loadSessionData === 'function') loadSessionData(s.session_id); },
        });
    });

    // Filter
    if (!q) return items.slice(0, 40);
    return items.filter(it => (it.label + ' ' + it.kind + ' ' + (it.hint || '')).toLowerCase().includes(q));
}

function clickTab(tabId) {
    const t = document.getElementById(tabId);
    if (t) t.click();
}

function renderCmdResults(query) {
    __cmdItems = buildCmdItems(query);
    __cmdActiveIdx = 0;
    const ul = document.getElementById('cmdResults');
    ul.replaceChildren();
    if (__cmdItems.length === 0) {
        ul.insertAdjacentHTML('beforeend', '<li class="cmd-empty">No matches</li>');
        return;
    }
    __cmdItems.forEach((it, i) => {
        const li = document.createElement('li');
        li.className = 'cmd-result' + (i === 0 ? ' is-active' : '');
        li.setAttribute('role', 'option');
        li.dataset.idx = String(i);
        li.insertAdjacentHTML('beforeend', `
            <span class="cmd-result-kind">${escapeHtml(it.kind)}</span>
            <span class="cmd-result-label">${escapeHtml(it.label)}</span>
            ${it.hint ? `<span class="cmd-result-hint">${escapeHtml(it.hint)}</span>` : ''}
        `);
        li.addEventListener('click', () => runCmdItem(i));
        li.addEventListener('mouseenter', () => setCmdActive(i));
        ul.appendChild(li);
    });
}

function setCmdActive(idx) {
    __cmdActiveIdx = idx;
    document.querySelectorAll('#cmdResults .cmd-result').forEach((el, i) =>
        el.classList.toggle('is-active', i === idx));
    const active = document.querySelector('#cmdResults .cmd-result.is-active');
    if (active) active.scrollIntoView({ block: 'nearest' });
}

function runCmdItem(idx) {
    const it = __cmdItems[idx];
    if (!it) return;
    closeCmdPalette();
    try { it.run(); } catch (e) { toast(String(e), 'error'); }
}

function wireCmdPalette() {
    const back = document.getElementById('cmdPalette');
    if (!back) return;
    const input = document.getElementById('cmdInput');
    back.addEventListener('click', e => { if (e.target === back) closeCmdPalette(); });
    input.addEventListener('input', () => renderCmdResults(input.value));
    input.addEventListener('keydown', e => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setCmdActive(Math.min(__cmdActiveIdx + 1, __cmdItems.length - 1));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setCmdActive(Math.max(__cmdActiveIdx - 1, 0));
        } else if (e.key === 'Enter') {
            e.preventDefault();
            runCmdItem(__cmdActiveIdx);
        } else if (e.key === 'Escape') {
            e.preventDefault();
            closeCmdPalette();
        }
    });
    document.addEventListener('keydown', e => {
        const isCmdK = (e.key === 'k' || e.key === 'K') && (e.metaKey || e.ctrlKey);
        if (isCmdK) {
            e.preventDefault();
            if (back.classList.contains('hidden')) openCmdPalette();
            else closeCmdPalette();
        }
    });
}

document.addEventListener('DOMContentLoaded', wireCmdPalette);

// =============================================================
// Phase C — Auth chip, logout, quota enforcement
// =============================================================
async function loadCurrentUser() {
    try {
        const res = await fetch('/api/auth/me');
        if (!res.ok) return null;
        const data = await res.json();
        window.__currentUser = data.user || null;
        if (data.quota) {
            window.__quota = data.quota;
            if (typeof renderQuota === 'function') renderQuota();
        }
        renderUserChip(window.__currentUser);
        return window.__currentUser;
    } catch (_) { return null; }
}

function renderUserChip(user) {
    const name = document.getElementById('userChipName');
    const avatar = document.getElementById('userAvatar');
    const menuName = document.getElementById('userMenuName');
    const menuEmail = document.getElementById('userMenuEmail');
    const settingsEmail = document.getElementById('settingsAccountEmail');
    const sideName = document.getElementById('sidebarUserName');
    const sideEmail = document.getElementById('sidebarUserEmail');
    const sideAvatar = document.getElementById('sidebarAvatar');
    if (!name || !avatar) return;
    if (!user) {
        name.textContent = 'Signed out';
        avatar.textContent = '·';
        if (settingsEmail) settingsEmail.textContent = '—';
        if (sideName) sideName.textContent = 'Signed out';
        if (sideEmail) sideEmail.textContent = '—';
        if (sideAvatar) sideAvatar.textContent = '·';
        return;
    }
    const display = user.display_name || (user.email || '').split('@')[0];
    const initial = (display[0] || '?').toUpperCase();
    name.textContent = display;
    avatar.textContent = initial;
    if (menuName) menuName.textContent = user.display_name || display;
    if (menuEmail) menuEmail.textContent = user.email || '';
    if (settingsEmail) settingsEmail.textContent = user.email || '';
    if (sideName) sideName.textContent = user.display_name || display;
    if (sideEmail) sideEmail.textContent = user.email || '';
    if (sideAvatar) sideAvatar.textContent = initial;
}

function wireUserMenu() {
    const chip = document.getElementById('userChip');
    const btn = document.getElementById('userChipBtn');
    const menu = document.getElementById('userMenu');
    if (!chip || !btn || !menu) {
        console.warn('[wireUserMenu] chip/btn/menu missing', { chip: !!chip, btn: !!btn, menu: !!menu });
        return;
    }

    // Boot state: menu starts hidden via inline display:none (overrides .hidden
    // class quirks). CSS reveals it via :focus-within OR .is-open.
    menu.classList.remove('hidden');           // remove legacy class
    menu.style.display = 'none';                // CSS rules will turn it on

    function openMenu() {
        chip.classList.add('is-open');
        menu.style.display = 'block';
        btn.setAttribute('aria-expanded', 'true');
    }
    function closeMenu() {
        chip.classList.remove('is-open');
        menu.style.display = 'none';
        btn.setAttribute('aria-expanded', 'false');
    }
    function toggleMenu(e) {
        if (e) { e.preventDefault(); e.stopPropagation(); }
        if (chip.classList.contains('is-open')) closeMenu(); else openMenu();
    }

    btn.addEventListener('click', toggleMenu);
    menu.addEventListener('click', (e) => e.stopPropagation());

    // Outside-click closes (capture phase so it beats other handlers).
    document.addEventListener('click', (e) => {
        if (!chip.classList.contains('is-open')) return;
        if (!chip.contains(e.target)) closeMenu();
    }, true);

    // Esc closes.
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && chip.classList.contains('is-open')) closeMenu();
    });

    // Logout — POST then redirect. Wire BOTH the dropdown item AND the
    // standalone "Log out" button on the Settings tab, so the user is never
    // stranded if the dropdown fails to open for any reason.
    async function doLogout(e) {
        if (e) { e.preventDefault(); e.stopPropagation(); }
        try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (_) {}
        window.location.href = '/login';
    }
    const logout = document.getElementById('logoutBtn');
    if (logout) logout.addEventListener('click', doLogout);
    const settingsLogout = document.getElementById('settingsLogoutBtn');
    if (settingsLogout) settingsLogout.addEventListener('click', doLogout);
    const sidebarLogout = document.getElementById('sidebarLogoutBtn');
    if (sidebarLogout) sidebarLogout.addEventListener('click', doLogout);
}

// Gate the "+ New Session" button against the quota.
function wireQuotaGuard() {
    const btn = document.getElementById('newSessionBtn');
    if (!btn) return;
    btn.addEventListener('click', (e) => {
        const q = window.__quota;
        if (q && q.at_limit) {
            // Don't block creating an empty workspace — just warn that submit will fail.
            toast(`Limit reached (${q.limit}). Delete a session before generating new tests.`,
                  'warn', 'Session quota full');
        }
    }, true /* capture so we run before any reset handler */);
}

// Global fetch error helper for 401 + 409 quota:
window.addEventListener('unhandledrejection', (e) => {
    // Best-effort; explicit handlers in fetch() chains do the heavy lifting.
});

document.addEventListener('DOMContentLoaded', () => {
    loadCurrentUser();
    wireUserMenu();
    wireQuotaGuard();
});

// =============================================================
// Phase D — 3D card tilt + ripple micro-interactions
// =============================================================

const __reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function wireTilt() {
    if (__reduceMotion) return;
    const cards = document.querySelectorAll('[data-tilt]');
    cards.forEach(card => {
        // Inject sheen overlay if it isn't already present.
        if (!card.querySelector('.tilt-sheen')) {
            const sheen = document.createElement('span');
            sheen.className = 'tilt-sheen';
            card.appendChild(sheen);
        }
        let rafId = null;
        card.addEventListener('mousemove', (e) => {
            const r = card.getBoundingClientRect();
            const x = (e.clientX - r.left) / r.width;
            const y = (e.clientY - r.top) / r.height;
            const tx = (x - 0.5) * 2;  // -1..1
            const ty = (y - 0.5) * 2;
            if (rafId) cancelAnimationFrame(rafId);
            rafId = requestAnimationFrame(() => {
                card.classList.add('is-tilting');
                card.style.transform =
                    `perspective(1000px) rotateX(${-ty * 4}deg) rotateY(${tx * 6}deg) translateY(-2px)`;
                card.style.setProperty('--mx', `${x * 100}%`);
                card.style.setProperty('--my', `${y * 100}%`);
            });
        });
        card.addEventListener('mouseleave', () => {
            card.classList.remove('is-tilting');
            card.style.transform = '';
        });
    });
}

function wireRipples() {
    document.addEventListener('click', (e) => {
        const target = e.target.closest('[data-ripple]');
        if (!target) return;
        const rect = target.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        const ink = document.createElement('span');
        ink.className = 'ripple-ink';
        ink.style.width = ink.style.height = size + 'px';
        ink.style.left = (e.clientX - rect.left - size / 2) + 'px';
        ink.style.top = (e.clientY - rect.top - size / 2) + 'px';
        target.appendChild(ink);
        setTimeout(() => ink.remove(), 600);
    });
}

// Auto-decorate primary CTAs and chips with ripple capability so we don't
// have to sprinkle data-ripple everywhere in HTML.
function autoDecorateRipples() {
    document.querySelectorAll('.primary-btn, .secondary-btn, .mini-btn, .chip, .auth-submit')
        .forEach(el => el.setAttribute('data-ripple', ''));
}

// Decorate cards that should tilt: glass cards, test-case cards in lists, stat boxes.
function autoDecorateTilt() {
    document.querySelectorAll('.stat-box').forEach(el => el.setAttribute('data-tilt', ''));
}

document.addEventListener('DOMContentLoaded', () => {
    autoDecorateRipples();
    autoDecorateTilt();
    wireTilt();
    wireRipples();
});

// Re-tilt cards rendered dynamically (e.g. after sessions/test cases load).
const __tiltRetagger = new MutationObserver(() => {
    autoDecorateRipples();
    autoDecorateTilt();
    wireTilt();
});
__tiltRetagger.observe(document.body, { childList: true, subtree: true });


// =============================================================
// Feature #11 — Bug tracker (JIRA / Linear) settings + state
// =============================================================
window.__ticketProviders = {};        // {jira: {...}, linear: {...}}

async function refreshTicketProviders() {
    try {
        const res = await fetch('/api/tickets/credentials');
        if (!res.ok) return;
        const data = await res.json();
        const map = {};
        (data.providers || []).forEach(p => { map[p.provider] = p; });
        window.__ticketProviders = map;
        renderTicketSettings();
    } catch (_) {}
}

function renderTicketSettings() {
    const J = window.__ticketProviders.jira || {};
    const L = window.__ticketProviders.linear || {};
    const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.value = v || ''; };
    setVal('jiraBaseUrl', J.base_url);
    setVal('jiraEmail', J.auth_email);
    setVal('jiraProject', J.default_project);
    setVal('linearTeam', L.default_project);
    // Tokens: only show a mask, don't refill the password field
    const jStat = document.getElementById('jiraStatus');
    if (jStat) {
        jStat.textContent = J.provider
            ? `Connected as ${J.auth_email || '?'} (token ${J.token_mask})`
            : 'Not configured';
        jStat.className = 'ticket-provider-status' + (J.provider ? ' is-ok' : '');
    }
    const lStat = document.getElementById('linearStatus');
    if (lStat) {
        lStat.textContent = L.provider
            ? `Token ${L.token_mask} — team ${L.default_project || '?'}`
            : 'Not configured';
        lStat.className = 'ticket-provider-status' + (L.provider ? ' is-ok' : '');
    }
}

async function saveTicketProvider(provider) {
    const payload = (provider === 'jira') ? {
        base_url:        document.getElementById('jiraBaseUrl').value.trim(),
        auth_email:      document.getElementById('jiraEmail').value.trim(),
        auth_token:      document.getElementById('jiraToken').value,
        default_project: document.getElementById('jiraProject').value.trim(),
    } : {
        auth_token:      document.getElementById('linearToken').value,
        default_project: document.getElementById('linearTeam').value.trim(),
    };
    const statusEl = document.getElementById(provider + 'Status');
    if (statusEl) { statusEl.textContent = 'Saving…'; statusEl.className = 'ticket-provider-status'; }
    try {
        const res = await fetch('/api/tickets/credentials/' + provider, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
        toast(`${provider.toUpperCase()} credentials saved.`, 'success', 'Bug tracker');
        // Clear the token field after a successful save (it lives in DB now)
        const tokenInput = document.getElementById(provider + (provider === 'jira' ? 'Token' : 'Token'));
        if (tokenInput) tokenInput.value = '';
        await refreshTicketProviders();
    } catch (e) {
        if (statusEl) { statusEl.textContent = e.message; statusEl.className = 'ticket-provider-status is-err'; }
        toast(e.message, 'error', 'Save failed');
    }
}

async function deleteTicketProvider(provider) {
    if (!confirm('Remove ' + provider.toUpperCase() + ' credentials?')) return;
    try {
        await fetch('/api/tickets/credentials/' + provider, { method: 'DELETE' });
        toast(`${provider.toUpperCase()} credentials removed.`, 'info');
        await refreshTicketProviders();
    } catch (_) {}
}

document.addEventListener('DOMContentLoaded', () => {
    refreshTicketProviders();
    const jSave = document.getElementById('jiraSaveBtn');
    if (jSave) jSave.addEventListener('click', () => saveTicketProvider('jira'));
    const jDel = document.getElementById('jiraDeleteBtn');
    if (jDel) jDel.addEventListener('click', () => deleteTicketProvider('jira'));
    const lSave = document.getElementById('linearSaveBtn');
    if (lSave) lSave.addEventListener('click', () => saveTicketProvider('linear'));
    const lDel = document.getElementById('linearDeleteBtn');
    if (lDel) lDel.addEventListener('click', () => deleteTicketProvider('linear'));
});

// =============================================================
// Feature #4 — Visual baselines settings panel
// =============================================================
// Build all DOM with createElement / textContent so untrusted name strings
// can never inject HTML (the backend already restricts names to
// /^[A-Za-z0-9._-]+$/, but defence in depth is cheap).

function _fmtBytes(n) {
    if (n == null) return '';
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / (1024 * 1024)).toFixed(2) + ' MB';
}

function _fmtAge(ts) {
    if (!ts) return '';
    const secs = Math.max(0, Date.now() / 1000 - ts);
    if (secs < 60)        return Math.round(secs) + 's ago';
    if (secs < 3600)      return Math.round(secs / 60) + 'm ago';
    if (secs < 86400)     return Math.round(secs / 3600) + 'h ago';
    return Math.round(secs / 86400) + 'd ago';
}

function _mkBtn(label, cls, action, name) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn btn-sm ' + cls;
    b.textContent = label;
    b.dataset.action = action;
    b.dataset.name = name;
    return b;
}

function _renderVisualCard(row) {
    const card = document.createElement('article');
    card.className = 'visual-baseline-card';

    const img = document.createElement('img');
    img.className = 'visual-baseline-thumb';
    img.loading = 'lazy';
    img.alt = 'baseline ' + row.name;
    img.src = '/api/visual/image?kind=baseline&name=' + encodeURIComponent(row.name);
    img.dataset.action = 'zoom';
    img.dataset.name = row.name;
    img.dataset.kind = 'baseline';
    card.appendChild(img);

    const body = document.createElement('div');
    body.className = 'visual-baseline-body';

    const nameDiv = document.createElement('div');
    nameDiv.className = 'visual-baseline-name';
    nameDiv.textContent = row.name;
    body.appendChild(nameDiv);

    const metaDiv = document.createElement('div');
    metaDiv.className = 'visual-baseline-meta';
    metaDiv.textContent = [
        row.width && row.height ? row.width + '×' + row.height : null,
        _fmtBytes(row.bytes),
        _fmtAge(row.mtime),
        row.sha256 ? 'sha:' + row.sha256 : null,
    ].filter(Boolean).join(' · ');
    body.appendChild(metaDiv);

    const actions = document.createElement('div');
    actions.className = 'visual-baseline-actions';
    if (row.has_diff)   actions.appendChild(_mkBtn('View diff', 'secondary-btn', 'view-diff', row.name));
    if (row.has_actual) actions.appendChild(_mkBtn('Promote actual', 'primary-btn', 'promote', row.name));
    actions.appendChild(_mkBtn('Delete', 'danger-btn', 'delete', row.name));
    body.appendChild(actions);

    card.appendChild(body);
    return card;
}

async function refreshVisualBaselines() {
    const root = document.getElementById('visualBaselinesList');
    if (!root) return;
    root.textContent = '';
    const loading = document.createElement('p');
    loading.className = 'settings-about';
    loading.textContent = 'Loading…';
    root.appendChild(loading);
    try {
        const res = await fetch('/api/visual/baselines');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        const rows = data.baselines || [];
        root.textContent = '';
        if (!rows.length) {
            const p = document.createElement('p');
            p.className = 'settings-about';
            p.textContent = 'No baselines yet. Add visual_baseline + assert_visual_match ops to your tests.';
            root.appendChild(p);
            return;
        }
        rows.forEach(r => root.appendChild(_renderVisualCard(r)));
        wireVisualBaselineActions(root);
    } catch (e) {
        root.textContent = '';
        const p = document.createElement('p');
        p.className = 'settings-about is-err';
        p.textContent = 'Failed to load baselines: ' + e.message;
        root.appendChild(p);
    }
}

function wireVisualBaselineActions(root) {
    root.querySelectorAll('[data-action="delete"]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const name = btn.dataset.name;
            if (!confirm('Delete baseline "' + name + '"? Next run will re-seed it.')) return;
            try {
                const r = await fetch('/api/visual/baselines/' + encodeURIComponent(name), { method: 'DELETE' });
                if (!r.ok) throw new Error('HTTP ' + r.status);
                toast('Baseline "' + name + '" deleted.', 'info', 'Visual');
                refreshVisualBaselines();
            } catch (e) { toast(e.message, 'error'); }
        });
    });
    root.querySelectorAll('[data-action="promote"]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const name = btn.dataset.name;
            if (!confirm('Promote the latest actual screenshot to baseline "' + name + '"?')) return;
            try {
                const r = await fetch('/api/visual/baselines/' + encodeURIComponent(name) + '/promote',
                                      { method: 'POST' });
                if (!r.ok) throw new Error('HTTP ' + r.status);
                toast('Baseline "' + name + '" promoted.', 'success', 'Visual');
                refreshVisualBaselines();
            } catch (e) { toast(e.message, 'error'); }
        });
    });
    root.querySelectorAll('[data-action="view-diff"]').forEach(btn => {
        btn.addEventListener('click', () => openVisualLightbox(btn.dataset.name, 'diff'));
    });
    root.querySelectorAll('[data-action="zoom"]').forEach(img => {
        img.addEventListener('click', () => openVisualLightbox(img.dataset.name, img.dataset.kind || 'baseline'));
    });
}

function openVisualLightbox(name, kind) {
    // Re-use the existing failure-screenshot lightbox.
    const lb = document.getElementById('lightbox');
    const img = document.getElementById('lightboxImg');
    if (!lb || !img) return;
    img.src = '/api/visual/image?kind=' + encodeURIComponent(kind) +
              '&name=' + encodeURIComponent(name) + '&_=' + Date.now();
    img.alt = kind + ' for ' + name;
    lb.classList.remove('hidden');
    lb.setAttribute('aria-hidden', 'false');
}

document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('refreshVisualBaselinesBtn');
    if (btn) btn.addEventListener('click', refreshVisualBaselines);
    // Lazy-load when the Settings tab becomes visible.
    const settingsTab = document.querySelector('[data-tab-target="settingsView"]');
    if (settingsTab) settingsTab.addEventListener('click', () => {
        setTimeout(refreshVisualBaselines, 50);
    });
    // First page load: if Settings is already active, populate.
    if (document.querySelector('#settingsView.active-view')) {
        refreshVisualBaselines();
    }
});

// =============================================================
// Feature #7 — Slack notifications + Scheduled runs
// =============================================================
function _setStatus(id, text, cls) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text || '';
    el.className = 'ticket-provider-status' + (cls ? ' ' + cls : '');
}

async function refreshSlackCreds() {
    try {
        const res = await fetch('/api/notifications/slack');
        if (!res.ok) return;
        const data = await res.json();
        const s = data.slack;
        if (!s) {
            _setStatus('slackStatus', 'Not configured');
            return;
        }
        const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.value = v || ''; };
        setVal('slackChannel', s.default_channel);
        setVal('slackMention', s.mention_on_fail);
        // Webhook field shows the masked URL; the user must paste a new one to update.
        const wh = document.getElementById('slackWebhookUrl');
        if (wh) wh.placeholder = s.webhook_mask || wh.placeholder;
        _setStatus('slackStatus', 'Connected (' + (s.webhook_mask || '') + ')', 'is-ok');
    } catch (_) {}
}

async function saveSlackCreds() {
    const wh = (document.getElementById('slackWebhookUrl').value || '').trim();
    if (!wh) { toast('Paste a webhook URL first.', 'warn'); return; }
    _setStatus('slackStatus', 'Saving…');
    try {
        const res = await fetch('/api/notifications/slack', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                webhook_url: wh,
                default_channel: document.getElementById('slackChannel').value.trim(),
                mention_on_fail: document.getElementById('slackMention').value.trim(),
            }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
        document.getElementById('slackWebhookUrl').value = '';
        toast('Slack webhook saved.', 'success');
        refreshSlackCreds();
    } catch (e) {
        _setStatus('slackStatus', e.message, 'is-err');
        toast(e.message, 'error');
    }
}

async function deleteSlackCreds() {
    if (!confirm('Remove Slack webhook?')) return;
    await fetch('/api/notifications/slack', { method: 'DELETE' });
    toast('Slack webhook removed.', 'info');
    document.getElementById('slackWebhookUrl').value = '';
    document.getElementById('slackChannel').value = '';
    document.getElementById('slackMention').value = '';
    refreshSlackCreds();
}

async function sendSlackTest() {
    _setStatus('slackStatus', 'Sending test message…');
    try {
        const res = await fetch('/api/notifications/slack/test', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
        _setStatus('slackStatus', 'Test message sent ✔', 'is-ok');
        toast('Test message posted to Slack.', 'success');
    } catch (e) {
        _setStatus('slackStatus', e.message, 'is-err');
        toast(e.message, 'error');
    }
}

// ---- Schedules list ----------------------------------------------

function _scheduleStatusBadge(status) {
    const span = document.createElement('span');
    span.className = 'schedule-status';
    if (status === 'ok')      { span.classList.add('is-ok');    span.textContent = 'last run: ok'; }
    else if (status === 'error') { span.classList.add('is-err'); span.textContent = 'last run: error'; }
    else if (status === 'broken') { span.classList.add('is-err'); span.textContent = 'broken expression'; }
    else if (status === 'missing-session') { span.classList.add('is-err'); span.textContent = 'session missing'; }
    else                     { span.textContent = status || 'pending'; }
    return span;
}

function _fmtTimestamp(ts) {
    if (!ts) return '—';
    try {
        const d = new Date(ts * 1000);
        return d.toLocaleString();
    } catch (_) { return String(ts); }
}

function _mkScheduleCard(row) {
    const card = document.createElement('article');
    card.className = 'schedule-card';
    card.dataset.id = row.id;

    const head = document.createElement('div');
    head.className = 'schedule-head';
    const expr = document.createElement('strong');
    expr.textContent = row.expression;
    head.appendChild(expr);
    head.appendChild(_scheduleStatusBadge(row.last_status));
    card.appendChild(head);

    const meta = document.createElement('div');
    meta.className = 'schedule-meta';
    meta.textContent = 'session ' + (row.session_id || '').slice(0, 8)
        + ' · next ' + _fmtTimestamp(row.next_run_at)
        + (row.last_run_at ? (' · last ' + _fmtTimestamp(row.last_run_at)) : '');
    card.appendChild(meta);

    if (row.last_error) {
        const err = document.createElement('div');
        err.className = 'schedule-error';
        err.textContent = row.last_error;
        card.appendChild(err);
    }

    const actions = document.createElement('div');
    actions.className = 'schedule-actions';

    const toggleBtn = document.createElement('button');
    toggleBtn.type = 'button';
    toggleBtn.className = 'btn btn-sm ' + (row.enabled ? 'secondary-btn' : 'primary-btn');
    toggleBtn.textContent = row.enabled ? 'Pause' : 'Resume';
    toggleBtn.addEventListener('click', () => toggleSchedule(row.id, !row.enabled));
    actions.appendChild(toggleBtn);

    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'btn btn-sm danger-btn';
    delBtn.textContent = 'Delete';
    delBtn.addEventListener('click', () => deleteSchedule(row.id));
    actions.appendChild(delBtn);

    card.appendChild(actions);
    return card;
}

async function refreshSchedules() {
    const root = document.getElementById('schedulesList');
    if (!root) return;
    root.textContent = '';
    try {
        const res = await fetch('/api/schedules');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        const rows = data.schedules || [];
        if (!rows.length) {
            const p = document.createElement('p');
            p.className = 'settings-about';
            p.textContent = 'No schedules yet. Use the Schedule button on a session to add one.';
            root.appendChild(p);
            return;
        }
        rows.forEach(r => root.appendChild(_mkScheduleCard(r)));
    } catch (e) {
        const p = document.createElement('p');
        p.className = 'settings-about is-err';
        p.textContent = 'Failed to load schedules: ' + e.message;
        root.appendChild(p);
    }
}

async function toggleSchedule(id, enabled) {
    try {
        const r = await fetch('/api/schedules/' + id + '/toggle', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({enabled}),
        });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        toast(enabled ? 'Schedule resumed.' : 'Schedule paused.', 'info');
        refreshSchedules();
    } catch (e) { toast(e.message, 'error'); }
}

async function deleteSchedule(id) {
    if (!confirm('Delete this schedule?')) return;
    try {
        await fetch('/api/schedules/' + id, { method: 'DELETE' });
        toast('Schedule deleted.', 'info');
        refreshSchedules();
    } catch (e) { toast(e.message, 'error'); }
}

async function createScheduleForSession(sessionId, expression, slackNotify) {
    try {
        const res = await fetch('/api/schedules', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                session_id: sessionId,
                expression: expression,
                slack_notify: !!slackNotify,
            }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
        toast('Scheduled: ' + (data.human || expression), 'success');
        return data;
    } catch (e) {
        toast(e.message, 'error');
        throw e;
    }
}

// Expose for the sidebar to call when the user clicks "Schedule" on a session.
window.createScheduleForSession = createScheduleForSession;
window.refreshSchedules = refreshSchedules;

// ---- Schedule modal -----------------------------------------------

let __schedulingSessionId = null;

function openScheduleModal(sessionId, featureLabel) {
    __schedulingSessionId = sessionId;
    const modal = document.getElementById('scheduleModal');
    if (!modal) return;
    const sub = document.getElementById('scheduleModalSubtitle');
    if (sub && featureLabel) {
        sub.textContent = 'Session: "' + featureLabel + '". Pick a cadence; results post to Slack if configured.';
    }
    document.getElementById('scheduleExprInput').value = 'every 6h';
    document.getElementById('scheduleSlackToggle').checked = true;
    document.getElementById('scheduleModalStatus').textContent = '';
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
}

function closeScheduleModal() {
    const modal = document.getElementById('scheduleModal');
    if (modal) { modal.classList.add('hidden'); modal.setAttribute('aria-hidden', 'true'); }
    __schedulingSessionId = null;
}

window.openScheduleModal = openScheduleModal;

document.addEventListener('DOMContentLoaded', () => {
    const modal = document.getElementById('scheduleModal');
    if (!modal) return;
    modal.querySelector('.modal-close').addEventListener('click', closeScheduleModal);
    document.getElementById('scheduleCancelBtn').addEventListener('click', closeScheduleModal);
    modal.querySelectorAll('.schedule-expr-presets [data-preset]').forEach(chip => {
        chip.addEventListener('click', () => {
            document.getElementById('scheduleExprInput').value = chip.dataset.preset;
        });
    });
    document.getElementById('scheduleSaveBtn').addEventListener('click', async () => {
        if (!__schedulingSessionId) return;
        const expr = (document.getElementById('scheduleExprInput').value || '').trim();
        const slack = document.getElementById('scheduleSlackToggle').checked;
        const status = document.getElementById('scheduleModalStatus');
        status.textContent = 'Saving…';
        try {
            await createScheduleForSession(__schedulingSessionId, expr, slack);
            status.textContent = 'Saved ✔';
            refreshSchedules();
            setTimeout(closeScheduleModal, 400);
        } catch (e) {
            status.textContent = e.message;
        }
    });
});

document.addEventListener('DOMContentLoaded', () => {
    // Slack wiring
    refreshSlackCreds();
    const sSave = document.getElementById('slackSaveBtn');
    if (sSave) sSave.addEventListener('click', saveSlackCreds);
    const sDel = document.getElementById('slackDeleteBtn');
    if (sDel) sDel.addEventListener('click', deleteSlackCreds);
    const sTest = document.getElementById('slackTestBtn');
    if (sTest) sTest.addEventListener('click', sendSlackTest);
    // Schedules wiring
    const refr = document.getElementById('refreshSchedulesBtn');
    if (refr) refr.addEventListener('click', refreshSchedules);
    const settingsTab = document.querySelector('[data-tab-target="settingsView"]');
    if (settingsTab) settingsTab.addEventListener('click', () => {
        setTimeout(() => { refreshSlackCreds(); refreshSchedules(); }, 60);
    });
    if (document.querySelector('#settingsView.active-view')) {
        refreshSchedules();
    }
});
