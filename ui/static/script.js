let currentSessionId = null;

// DOM Elements
const sessionList = document.getElementById('sessionList');
const newSessionBtn = document.getElementById('newSessionBtn');
const featureInput = document.getElementById('featureInput');
const generateBtn = document.getElementById('generateBtn');

const welcomeState = document.getElementById('welcomeState');
const activeSessionState = document.getElementById('activeSessionState');
const activeSessionTitle = document.getElementById('activeSessionTitle');
const activeSessionStatus = document.getElementById('activeSessionStatus');
const testCasesContainer = document.getElementById('testCasesContainer');
const automationPrompt = document.getElementById('automationPrompt');
const runAutomationBtn = document.getElementById('runAutomationBtn');
const envSelect = document.getElementById('envSelect');

const globalReportsContainer = document.getElementById('globalReportsContainer');
const modal = document.getElementById('reportModal');
const closeModalBtn = document.querySelector('.close-modal');

// Tabs
const navTabs = document.querySelectorAll('.nav-tab');
const viewPanels = document.querySelectorAll('.view-panel');

document.addEventListener('DOMContentLoaded', () => {
    loadSessions();
});

// Navigation Logic
navTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        navTabs.forEach(t => t.classList.remove('active'));
        viewPanels.forEach(p => p.classList.remove('active-view'));
        
        tab.classList.add('active');
        document.getElementById(tab.dataset.target).classList.add('active-view');
        
        if (tab.dataset.target === 'reportsView') {
            loadGlobalReports();
        }
    });
});

// Session Management
newSessionBtn.addEventListener('click', () => {
    currentSessionId = null;
    featureInput.value = '';
    welcomeState.classList.remove('hidden');
    activeSessionState.classList.add('hidden');
    document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
    document.querySelector('[data-target="dashboardView"]').click();
});

async function loadSessions() {
    try {
        const res = await fetch('/api/sessions');
        const sessions = await res.json();
        sessionList.innerHTML = '';
        sessions.forEach(s => {
            const li = document.createElement('li');
            li.className = 'session-item';
            li.innerHTML = `
                <span>${s.feature || "Unnamed Session"}</span>
                <button class="delete-btn" title="Delete Session">🗑️</button>
            `;
            
            li.addEventListener('click', (e) => {
                if (e.target.classList.contains('delete-btn') || e.target.closest('.delete-btn')) {
                    deleteSession(s.session_id, li);
                    return;
                }
                loadSessionData(s.session_id);
                document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
                li.classList.add('active');
            });
            sessionList.appendChild(li);
        });
    } catch (err) {
        console.error("Failed to load sessions:", err);
    }
}

async function deleteSession(id, listElement) {
    if(!confirm("Are you sure you want to delete this session?")) return;
    try {
        await fetch(`/api/sessions/${id}`, { method: 'DELETE' });
        listElement.remove();
        if(currentSessionId === id) newSessionBtn.click();
    } catch(err) {
        console.error(err);
    }
}

async function loadSessionData(id) {
    document.querySelector('[data-target="dashboardView"]').click();
    welcomeState.classList.add('hidden');
    activeSessionState.classList.remove('hidden');
    testCasesContainer.innerHTML = 'Loading...';
    automationPrompt.classList.add('hidden');
    currentSessionId = id;

    try {
        const res = await fetch(`/api/sessions/${id}`);
        const session = await res.json();
        
        activeSessionTitle.innerText = session.feature;
        activeSessionStatus.innerText = session.state;
        
        renderTestCases(session.test_cases);
        
        if (session.state === 'GENERATED') {
            automationPrompt.classList.remove('hidden');
        } else if (session.state === 'EXECUTED' && session.report) {
            renderReportInline(session.report);
        }
    } catch (err) {
        testCasesContainer.innerHTML = 'Error loading session data.';
    }
}

// Generating Tests
generateBtn.addEventListener('click', async () => {
    const text = featureInput.value.trim();
    if(!text) return;
    
    welcomeState.classList.add('hidden');
    activeSessionState.classList.remove('hidden');
    activeSessionTitle.innerText = text;
    activeSessionStatus.innerText = "GENERATING...";
    testCasesContainer.innerHTML = '<p style="color:var(--text-secondary)">TestCaseGeneratorAgent is creating the suite...</p>';
    automationPrompt.classList.add('hidden');
    featureInput.value = '';

    try {
        const res = await fetch('/api/generate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ feature: text })
        });
        const data = await res.json();
        if(data.error) throw new Error(data.error);

        currentSessionId = data.session.session_id;
        activeSessionStatus.innerText = data.session.state;
        renderTestCases(data.session.test_cases);
        automationPrompt.classList.remove('hidden');
        loadSessions();
    } catch (err) {
        testCasesContainer.innerHTML = `<p style="color:var(--fail)">${err.message}</p>`;
    }
});

// Executing Tests
runAutomationBtn.addEventListener('click', async () => {
    if(!currentSessionId) return;
    const env = envSelect.value;
    
    automationPrompt.classList.add('hidden');
    activeSessionStatus.innerText = "EXECUTING...";
    
    try {
        const res = await fetch(`/api/execute/${currentSessionId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ environment: env })
        });
        const data = await res.json();
        if(data.error) throw new Error(data.error);
        
        activeSessionStatus.innerText = data.session.state;
        renderTestCases(data.session.test_cases);
        if(data.session.report) renderReportInline(data.session.report);
        
    } catch (err) {
        alert(err.message);
        activeSessionStatus.innerText = "GENERATED (Failed Execution)";
        automationPrompt.classList.remove('hidden');
    }
});

// Rendering UI
function renderTestCases(cases) {
    if(!cases || cases.length === 0) {
        testCasesContainer.innerHTML = 'No test cases generated.';
        return;
    }
    testCasesContainer.innerHTML = '';
    cases.forEach(tc => {
        let statusBadge = tc.status === 'Pass' ? `<span style="color:var(--pass)">[PASS]</span>` : 
                          tc.status === 'Fail' ? `<span style="color:var(--fail)">[FAIL]</span>` : 
                          `<span style="color:var(--text-secondary)">[${tc.status}]</span>`;
                          
        let errorMarkup = tc.error ? `<div style="color:var(--fail); margin-top:10px;">Error: ${tc.error}</div>` : "";
        let aiInsight = tc.bug_insight ? `<div style="background:rgba(239, 68, 68, 0.1); padding:10px; border-left:3px solid var(--fail); margin-top:10px; font-size:0.9rem;"><strong>AI Analysis:</strong> ${tc.bug_insight}</div>` : "";

        const html = `
            <div class="test-case-card">
                <div class="tc-header">
                    <strong>${tc.id}</strong>
                    <span class="tc-type">${tc.type}</span>
                    ${statusBadge}
                </div>
                <div class="tc-desc">${tc.description}</div>
                <ul style="margin-left: 20px; font-size:0.9rem; color:var(--text-secondary); margin-bottom:10px;">
                    ${tc.steps.map(step => `<li>${step}</li>`).join('')}
                </ul>
                <div style="font-size:0.9rem;"><strong>Expected:</strong> ${tc.expected}</div>
                ${errorMarkup}
                ${aiInsight}
                <details>
                    <summary style="cursor:pointer; color:var(--accent); font-size:0.85rem; margin-top:10px;">View Python Code</summary>
                    <pre class="tc-code">${tc.selenium_action}</pre>
                </details>
            </div>
        `;
        testCasesContainer.insertAdjacentHTML('beforeend', html);
    });
}

function renderReportInline(report) {
    const html = `
        <div style="background:var(--bg-panel); border:1px solid var(--glass-border); padding:1.5rem; border-radius:12px; margin-top:2rem;">
            <h3 style="color:var(--accent); margin-bottom:15px;">Executive Report</h3>
            <div style="display:flex; gap:20px; margin-bottom:15px;">
                <div style="font-size:1.5rem; font-weight:bold;">Total: ${report.metrics.total}</div>
                <div style="font-size:1.5rem; font-weight:bold; color:var(--pass);">Pass: ${report.metrics.passed}</div>
                <div style="font-size:1.5rem; font-weight:bold; color:var(--fail);">Fail: ${report.metrics.failed}</div>
            </div>
            <p>${report.executive_summary}</p>
        </div>
    `;
    testCasesContainer.insertAdjacentHTML('beforeend', html);
}

// Global Reports View
async function loadGlobalReports() {
    const healthCtx = document.getElementById('healthChart');
    if(window.healthChartInstance) window.healthChartInstance.destroy();
    
    document.getElementById('rTotal').innerText = "Loading...";
    document.getElementById('rPassRate').innerText = "...";
    document.getElementById('rFail').innerText = "...";
    
    try {
        const res = await fetch('/api/reports/global_insights');
        const data = await res.json();
        
        document.getElementById('rTotal').innerText = data.total_evaluated;
        document.getElementById('rPassRate').innerText = data.pass_rate + "%";
        document.getElementById('rFail').innerText = data.total_failures;
        
        window.healthChartInstance = new Chart(healthCtx, {
            type: 'doughnut',
            data: {
                labels: ['Passed', 'Failed'],
                datasets: [{
                    data: [data.total_evaluated - data.total_failures, data.total_failures],
                    backgroundColor: ['#4ade80', '#ef4444'],
                    borderColor: '#121212',
                    borderWidth: 2
                }]
            },
            options: { cutout: '75%', responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { color: '#fff' } } } }
        });
        
        const failList = document.getElementById('mostFailingList');
        failList.innerHTML = '';
        if (data.most_failing_tests && data.most_failing_tests.length > 0) {
            data.most_failing_tests.forEach(ft => {
                failList.insertAdjacentHTML('beforeend', `
                    <li style="background:var(--bg-panel); border-left:3px solid var(--fail); padding:10px; margin-bottom:10px;">
                        <strong>${ft.test_id}</strong> (${ft.session})<br>
                        <span style="color:var(--text-secondary); font-size:0.85rem">${ft.error}</span><br>
                        <span style="color:var(--accent); font-size:0.85rem">Analyst Insight: ${ft.isolated_insight}</span>
                    </li>
                `);
            });
        } else {
            failList.innerHTML = '<li style="color:var(--text-secondary)">No failing tests registered.</li>';
        }
        
        const pContainer = document.getElementById('aiBugPatterns');
        pContainer.innerHTML = '';
        data.bug_patterns.forEach(pt => {
            pContainer.insertAdjacentHTML('beforeend', `<div>• ${pt}</div>`);
        });
        
        document.getElementById('aiSuggestions').innerText = data.ai_suggestions || "No suggestions derived.";
        
    } catch(err) {
        document.getElementById('rTotal').innerText = "Error loading insights";
    }
}

async function openReportModal(sessionId) {
    modal.classList.remove('hidden');
    document.getElementById('modalSessionTitle').innerText = 'Loading...';
    try {
        const res = await fetch(`/api/sessions/${sessionId}`);
        const session = await res.json();
        const report = session.report;
        
        document.getElementById('modalSessionTitle').innerText = `Report: ${session.feature}`;
        
        if(!report) {
            document.getElementById('modalSummary').innerText = "Report generation failed or incomplete.";
            return;
        }

        document.getElementById('mPass').innerText = report.metrics.passed;
        document.getElementById('mFail').innerText = report.metrics.failed;
        document.getElementById('mSkip').innerText = report.metrics.skipped;
        document.getElementById('modalSummary').innerText = report.executive_summary || "No summary provided.";
        
        const fContainer = document.getElementById('modalFailures');
        fContainer.innerHTML = '';
        const failedCases = session.test_cases.filter(tc => tc.status === 'Fail');
        if(failedCases.length === 0) {
            fContainer.innerHTML = '<p>No failures in this suite.</p>';
        } else {
            failedCases.forEach(fc => {
                fContainer.insertAdjacentHTML('beforeend', `
                    <div style="background:rgba(255,255,255,0.05); padding:10px; border-left:3px solid var(--fail); margin-bottom:10px;">
                        <strong>${fc.id}</strong>: ${fc.error}<br>
                        <em style="color:var(--text-secondary)">Insight: ${fc.bug_insight}</em>
                    </div>
                `);
            });
        }
        
    } catch(err) {
        document.getElementById('modalSummary').innerText = 'Failed to load report data.';
    }
}

closeModalBtn.onclick = () => modal.classList.add('hidden');
window.onclick = (e) => { if(e.target === modal) modal.classList.add('hidden'); }

// -----------------------------------------
// Automated (Direct Execution) Logic
// -----------------------------------------
const directFeatureInput = document.getElementById('directFeatureInput');
const directJsonInput = document.getElementById('directJsonInput');
const directRunBtn = document.getElementById('directRunBtn');
const directStatus = document.getElementById('directStatus');

directRunBtn.addEventListener('click', async () => {
    const rawVal = directJsonInput.value.trim();
    if (!rawVal) return;
    
    let parsedCases;
    try {
        parsedCases = JSON.parse(rawVal);
        if(!Array.isArray(parsedCases)) throw new Error("JSON must be an array of test cases.");
    } catch(err) {
        directStatus.style.color = "var(--fail)";
        directStatus.innerText = "Invalid JSON structure: " + err.message;
        return;
    }
    
    const feat = directFeatureInput.value.trim() || "Automated Direct Execution";
    const env = envSelect.value;
    
    directStatus.style.color = "var(--accent)";
    directStatus.innerText = "Processing automation execution directly...";
    directRunBtn.disabled = true;
    
    try {
        const res = await fetch('/api/execute_direct', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ feature: feat, environment: env, test_cases: parsedCases })
        });
        const data = await res.json();
        if(data.error) throw new Error(data.error);
        
        // Execution Complete, refresh sidebar and jump to Dashboard to show active session
        document.querySelector('.nav-tab[data-target="dashboardView"]').click();
        loadSessions();
        setTimeout(() => loadSessionData(data.session.session_id), 100);
        
    } catch (err) {
        directStatus.style.color = "var(--fail)";
        directStatus.innerText = "Execution failed: " + err.message;
    } finally {
        directRunBtn.disabled = false;
        directStatus.innerText = "";
    }
});

// -----------------------------------------
// Zero-Touch Automation Logic
// -----------------------------------------
const zeroTouchInput = document.getElementById('zeroTouchInput');
const zeroTouchBtn = document.getElementById('zeroTouchBtn');
const zeroTouchStatus = document.getElementById('zeroTouchStatus');

zeroTouchBtn.addEventListener('click', async () => {
    const feat = zeroTouchInput.value.trim();
    if (!feat) return;
    
    zeroTouchStatus.style.color = "var(--accent)";
    zeroTouchStatus.innerText = "Generating and Executing end-to-end automatically... Please wait.";
    zeroTouchBtn.disabled = true;
    
    try {
        const res = await fetch('/api/zero_touch', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ feature: feat, environment: envSelect.value })
        });
        const data = await res.json();
        if(data.error) throw new Error(data.error);
        
        // Zero-Touch Complete, refresh sidebar and jump to Dashboard to show active session
        document.querySelector('.nav-tab[data-target="dashboardView"]').click();
        loadSessions();
        setTimeout(() => loadSessionData(data.session.session_id), 100);
        
    } catch (err) {
        zeroTouchStatus.style.color = "var(--fail)";
        zeroTouchStatus.innerText = "Zero-Touch failed: " + err.message;
    } finally {
        zeroTouchBtn.disabled = false;
        setTimeout(() => zeroTouchStatus.innerText = "", 5000);
    }
});

// -----------------------------------------
// URL Auto Testing Logic
// -----------------------------------------
const urlAutoInput = document.getElementById('urlAutoInput');
const urlAutoBtn = document.getElementById('urlAutoBtn');
const urlAutoStatus = document.getElementById('urlAutoStatus');

urlAutoBtn.addEventListener('click', async () => {
    const targetUrl = urlAutoInput.value.trim();
    if (!targetUrl) return;
    
    urlAutoStatus.style.color = "var(--accent)";
    urlAutoStatus.innerText = "Initializing headless crawler... Harvesting DOM... Generative AI processing... Please wait.";
    urlAutoBtn.disabled = true;
    
    try {
        const res = await fetch('/api/url_auto', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ url: targetUrl })
        });
        const data = await res.json();
        if(data.error) throw new Error(data.error);
        
        document.querySelector('.nav-tab[data-target="dashboardView"]').click();
        loadSessions();
        setTimeout(() => loadSessionData(data.session.session_id), 100);
        
    } catch (err) {
        urlAutoStatus.style.color = "var(--fail)";
        urlAutoStatus.innerText = "Scrape failed: " + err.message;
    } finally {
        urlAutoBtn.disabled = false;
        setTimeout(() => urlAutoStatus.innerText = "", 7000);
    }
});
