// Auth page controller — tab toggle + submit handlers.
(function () {
    const tabs = document.querySelector('.auth-tabs');
    const tabLogin = document.getElementById('authTabLogin');
    const tabSignup = document.getElementById('authTabSignup');
    const formLogin = document.getElementById('loginForm');
    const formSignup = document.getElementById('signupForm');
    const subtitle = document.getElementById('authSubtitle');

    function setMode(mode) {
        const signup = mode === 'signup';
        tabs.classList.toggle('is-signup', signup);
        tabLogin.classList.toggle('active', !signup);
        tabSignup.classList.toggle('active', signup);
        tabLogin.setAttribute('aria-selected', String(!signup));
        tabSignup.setAttribute('aria-selected', String(signup));
        formLogin.classList.toggle('active', !signup);
        formSignup.classList.toggle('active', signup);
        if (signup) { formLogin.setAttribute('hidden', ''); formSignup.removeAttribute('hidden'); }
        else        { formSignup.setAttribute('hidden', ''); formLogin.removeAttribute('hidden'); }
        subtitle.textContent = signup
            ? 'Create your AbhiMate workspace in seconds.'
            : 'Sign in to your testing workspace.';
        const url = signup ? '/signup' : '/login';
        if (window.location.pathname !== url) {
            window.history.replaceState({}, '', url);
        }
    }

    tabLogin.addEventListener('click', () => setMode('login'));
    tabSignup.addEventListener('click', () => setMode('signup'));
    setMode(window.__INITIAL_AUTH_MODE || 'login');

    // 3D tilt
    const card = document.querySelector('[data-tilt]');
    if (card && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        card.addEventListener('mousemove', (e) => {
            const r = card.getBoundingClientRect();
            const x = (e.clientX - r.left) / r.width - 0.5;
            const y = (e.clientY - r.top) / r.height - 0.5;
            card.style.transform = `perspective(1000px) rotateX(${-y * 6}deg) rotateY(${x * 8}deg) translateY(-2px)`;
        });
        card.addEventListener('mouseleave', () => { card.style.transform = ''; });
    }

    async function submitForm(form, url, errEl, submitBtn) {
        errEl.textContent = '';
        submitBtn.disabled = true;
        submitBtn.querySelector('.auth-spinner').classList.remove('hidden');
        const body = {};
        new FormData(form).forEach((v, k) => { body[k] = v; });
        try {
            const res = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.error || 'Something went wrong.');
            window.location.href = '/';
        } catch (e) {
            errEl.textContent = e.message;
        } finally {
            submitBtn.disabled = false;
            submitBtn.querySelector('.auth-spinner').classList.add('hidden');
        }
    }

    formLogin.addEventListener('submit', (e) => {
        e.preventDefault();
        submitForm(formLogin, '/api/auth/login',
                   document.getElementById('loginError'),
                   formLogin.querySelector('.auth-submit'));
    });
    formSignup.addEventListener('submit', (e) => {
        e.preventDefault();
        submitForm(formSignup, '/api/auth/signup',
                   document.getElementById('signupError'),
                   formSignup.querySelector('.auth-submit'));
    });

    // One-click live demo — read-only guest account, no signup.
    const demoBtn = document.getElementById('demoBtn');
    if (demoBtn) {
        demoBtn.addEventListener('click', async () => {
            demoBtn.disabled = true;
            const spin = document.getElementById('demoSpinner');
            const txt = demoBtn.querySelector('.auth-demo-text');
            if (spin) spin.classList.remove('hidden');
            if (txt) txt.textContent = 'Loading demo…';
            try {
                const res = await fetch('/api/auth/demo', { method: 'POST' });
                if (!res.ok) throw new Error('Demo unavailable. Try again.');
                window.location.href = '/';
            } catch (e) {
                demoBtn.disabled = false;
                if (spin) spin.classList.add('hidden');
                if (txt) txt.textContent = '🎬 Try the live demo';
                const err = document.getElementById('loginError');
                if (err) err.textContent = e.message;
            }
        });
    }
})();
