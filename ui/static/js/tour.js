// Guided tour ("demo") — short spotlight walkthrough per tab.
// First visit to each tab auto-runs its tour (once, remembered in localStorage).
// A "?" button in the nav replays the current tab's tour anytime.
(function () {
    const SEEN_KEY = 'abhimate.tour.v1.';

    // Steps per view. selector is optional — if the element isn't on the page,
    // the step renders as a centered card instead of a spotlight, so the tour
    // never breaks across layout changes.
    const TOURS = {
        dashboardView: [
            { selector: '#featureInput',
              title: 'Describe what to test',
              text: 'Type a feature in plain English or Hinglish — or paste a URL. AI turns it into a full BDD test suite.' },
            { selector: '#caseCountSelect',
              title: 'Choose how many cases',
              text: 'Pick how many test cases the AI should generate (5–50).' },
            { selector: '#workersSelect',
              title: 'Run in parallel',
              text: 'Run cases across multiple browsers at once for a big speed-up. 1 = sequential.' },
            { selector: '#recordingChip',
              title: 'More ways to start',
              text: 'Generate from a screenshot, import a Chrome recording, or try an example chip.' },
            { selector: '#generateBtn',
              title: 'Generate',
              text: 'Hit send — your Gherkin test cases appear in seconds. Tick "Generate + Run" to execute them too.' },
        ],
        automatedView: [
            { title: 'Runs & history',
              text: 'This tab keeps your execution history. Re-run sessions, compare two runs with Run Diff, and explore data-driven variants.' },
        ],
        globalStatsView: [
            { title: 'Insights',
              text: 'AI analyses every failure across your sessions, surfaces recurring bug patterns, and shows your self-healing locator cache.' },
        ],
        settingsView: [
            { title: 'Settings',
              text: 'Configure Slack alerts, scheduled runs, visual baselines, the mobile device preset, and Jira/GitHub/Linear bug-tracker integrations.' },
        ],
    };

    let els = null;       // {overlay, spot, tip}
    let steps = [];
    let idx = 0;
    let viewId = null;

    function seen(v) { try { return localStorage.getItem(SEEN_KEY + v) === '1'; } catch (_) { return false; } }
    function markSeen(v) { try { localStorage.setItem(SEEN_KEY + v, '1'); } catch (_) {} }

    function build() {
        if (els) return els;
        const overlay = document.createElement('div');
        overlay.className = 'tour-overlay';
        const spot = document.createElement('div');
        spot.className = 'tour-spot';
        const tip = document.createElement('div');
        tip.className = 'tour-tip';
        overlay.appendChild(spot);
        overlay.appendChild(tip);
        document.body.appendChild(overlay);
        els = { overlay, spot, tip };
        return els;
    }

    function end() {
        if (els) els.overlay.classList.remove('visible');
        if (viewId) markSeen(viewId);
        document.removeEventListener('keydown', onKey);
        window.removeEventListener('resize', position);
    }

    function onKey(e) {
        if (e.key === 'Escape') end();
        else if (e.key === 'Enter' || e.key === 'ArrowRight') next();
        else if (e.key === 'ArrowLeft') prev();
    }

    function next() { if (idx < steps.length - 1) { idx++; render(); } else { end(); } }
    function prev() { if (idx > 0) { idx--; render(); } }

    function position() {
        if (!els) return;
        const step = steps[idx];
        const target = step.selector ? document.querySelector(step.selector) : null;
        const { spot, tip } = els;
        if (target && target.offsetParent !== null) {
            const r = target.getBoundingClientRect();
            const pad = 6;
            spot.style.display = 'block';
            spot.style.top = (r.top - pad) + 'px';
            spot.style.left = (r.left - pad) + 'px';
            spot.style.width = (r.width + pad * 2) + 'px';
            spot.style.height = (r.height + pad * 2) + 'px';
            // Place tip below the target, or above if low on screen.
            tip.style.maxWidth = '320px';
            const below = r.bottom + 12;
            const tipH = tip.offsetHeight || 160;
            if (below + tipH < window.innerHeight) {
                tip.style.top = below + 'px';
            } else {
                tip.style.top = Math.max(12, r.top - tipH - 12) + 'px';
            }
            let left = r.left;
            left = Math.min(left, window.innerWidth - (tip.offsetWidth || 320) - 16);
            tip.style.left = Math.max(16, left) + 'px';
        } else {
            // Centered card (no spotlight).
            spot.style.display = 'none';
            tip.style.maxWidth = '380px';
            tip.style.top = '50%';
            tip.style.left = '50%';
            tip.style.transform = 'translate(-50%, -50%)';
        }
    }

    function render() {
        const { tip } = build();
        const step = steps[idx];
        const isLast = idx === steps.length - 1;
        const target = step.selector ? document.querySelector(step.selector) : null;
        tip.style.transform = (target && target.offsetParent !== null) ? 'none' : 'translate(-50%, -50%)';
        tip.replaceChildren();

        const h = document.createElement('div');
        h.className = 'tour-tip-title';
        h.textContent = step.title;
        const p = document.createElement('p');
        p.className = 'tour-tip-text';
        p.textContent = step.text;

        const foot = document.createElement('div');
        foot.className = 'tour-tip-foot';
        const count = document.createElement('span');
        count.className = 'tour-tip-count';
        count.textContent = `${idx + 1} / ${steps.length}`;

        const btns = document.createElement('div');
        btns.className = 'tour-tip-btns';
        const skip = document.createElement('button');
        skip.type = 'button'; skip.className = 'tour-btn tour-btn-ghost';
        skip.textContent = 'Skip'; skip.addEventListener('click', end);
        if (idx > 0) {
            const back = document.createElement('button');
            back.type = 'button'; back.className = 'tour-btn tour-btn-ghost';
            back.textContent = 'Back'; back.addEventListener('click', prev);
            btns.appendChild(back);
        }
        const nextBtn = document.createElement('button');
        nextBtn.type = 'button'; nextBtn.className = 'tour-btn tour-btn-primary';
        nextBtn.textContent = isLast ? 'Got it' : 'Next';
        nextBtn.addEventListener('click', next);
        btns.appendChild(skip);
        btns.appendChild(nextBtn);

        foot.appendChild(count);
        foot.appendChild(btns);
        tip.appendChild(h);
        tip.appendChild(p);
        tip.appendChild(foot);
        position();
    }

    function start(v, opts) {
        const list = TOURS[v];
        if (!list || !list.length) return;
        if (!opts?.force && seen(v)) return;
        viewId = v;
        steps = list.slice();
        idx = 0;
        const { overlay } = build();
        overlay.classList.add('visible');
        // Clicking the dim area (not the tip) advances.
        overlay.onclick = (e) => { if (e.target === overlay) next(); };
        document.addEventListener('keydown', onKey);
        window.addEventListener('resize', position);
        // Defer one frame so the just-activated view is laid out.
        requestAnimationFrame(() => requestAnimationFrame(render));
    }

    // Auto-run on first visit to each tab.
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const v = tab.dataset.target;
            setTimeout(() => start(v), 250);
        });
    });

    // "?" replay button in the nav.
    const help = document.getElementById('tourHelpBtn');
    if (help) {
        help.addEventListener('click', () => {
            const active = document.querySelector('.view-panel.active-view');
            const v = active ? active.id : 'dashboardView';
            start(v, { force: true });
        });
    }

    // First load → Tests tour (once).
    window.addEventListener('load', () => setTimeout(() => start('dashboardView'), 600));

    window.startTour = start;   // expose for manual triggers
})();
