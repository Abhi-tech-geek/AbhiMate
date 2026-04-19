let currentSessionId = null;

// DOM Elements
const sessionList = document.getElementById('sessionList');
const newSessionBtn = document.getElementById('newSessionBtn');
const featureInput = document.getElementById('featureInput');
const generateBtn = document.getElementById('generateBtn');
const autoExecuteCheck = document.getElementById('autoExecuteCheck');

const welcomeState = document.getElementById('welcomeState');
const activeSessionState = document.getElementById('activeSessionState');
const activeSessionTitle = document.getElementById('activeSessionTitle');
const activeSessionStatus = document.getElementById('activeSessionStatus');
const testCasesContainer = document.getElementById('testCasesContainer');
const automationPrompt = document.getElementById('automationPrompt');
const runAutomationBtn = document.getElementById('runAutomationBtn');
const automationResultsContainer = document.getElementById('automationResultsContainer');

const sidebarToggle = document.getElementById('sidebarToggle');
const mainSidebar = document.getElementById('mainSidebar');
const navToReportsBtn = document.getElementById('navToReportsBtn');

// Nav/Settings Elements
const langSelect = document.getElementById('langSelect');
const modelSelect = document.getElementById('modelSelect');
const envSelect = document.getElementById('envSelect');

// Tabs
const navTabs = document.querySelectorAll('.nav-tab');
const viewPanels = document.querySelectorAll('.view-panel');

document.addEventListener('DOMContentLoaded', () => {
    loadSessions();
    loadGlobalInsights();
});

// Navigation Logic
navTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        navTabs.forEach(t => t.classList.remove('active'));
        viewPanels.forEach(p => p.classList.remove('active-view'));
        
        tab.classList.add('active');
        document.getElementById(tab.dataset.target).classList.add('active-view');
        
        if (tab.dataset.target === 'globalStatsView') {
            loadGlobalInsights();
        }
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

async function loadGlobalInsights() {
    try {
        const res = await fetch('/api/reports/global_insights');
        const stats = await res.json();
        document.getElementById('mTotal').innerText = stats.total_evaluated || 0;
        document.getElementById('mPassRate').innerText = `${stats.pass_rate || 0}%`;
        document.getElementById('mBugs').innerText = (stats.most_failing_tests || []).length;
    } catch (e) {
        console.error("Stats fetching failed.", e);
    }
}

async function deleteSession(id, listElement) {
    if(!confirm("Are you sure you want to delete this session?")) return;
    try {
        await fetch(`/api/sessions/${id}`, { method: 'DELETE' });
        listElement.remove();
        if(currentSessionId === id) newSessionBtn.click();
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
    testCasesContainer.innerHTML = '<p style="color:var(--text-secondary)">Agents are assembling test arrays... Please wait.</p>';
    automationPrompt.classList.add('hidden');
    featureInput.value = '';

    const payload = {
        prompt: text,
        autoRun: autoExecuteCheck.checked,
        environment: envSelect.value,
        model: modelSelect.value,
        lang: langSelect.value
    };

    try {
        const res = await fetch('/api/smart_input', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const data = await res.json();
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
        testCasesContainer.innerHTML = `<p style="color:var(--fail)">${err.message}</p>`;
    }
});

// Force Executing Tests (Manual trigger)
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
        renderTestCases(data.session.test_cases, testCasesContainer);
        if(data.session.report) renderReportInline(data.session.report, testCasesContainer);
        loadGlobalInsights();
    } catch (err) {
        alert(err.message);
        activeSessionStatus.innerText = "GENERATED (Failed Execution)";
        automationPrompt.classList.remove('hidden');
    }
});

// Rendering UI
function renderTestCases(cases, containerElement) {
    if(!cases || cases.length === 0) {
        containerElement.innerHTML = 'No test cases generated.';
        return;
    }
    containerElement.innerHTML = '';
    cases.forEach(tc => {
        let statusBadge = tc.status === 'Pass' ? `<span style="color:var(--pass)">[PASS]</span>` : 
                          tc.status === 'Fail' ? `<span style="color:var(--fail)">[FAIL]</span>` : 
                          `<span style="color:var(--text-secondary)">[${tc.status}]</span>`;
                          
        let errorMarkup = tc.error ? `<div style="color:var(--fail); margin-top:10px;">Error: ${tc.error}</div>` : "";
        let aiInsight = tc.bug_insight ? `<div style="background:rgba(239, 68, 68, 0.1); padding:10px; border-left:3px solid var(--fail); margin-top:10px; font-size:0.9rem;"><strong>AI Advanced Analysis:</strong> ${tc.bug_insight}</div>` : "";

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
        containerElement.insertAdjacentHTML('beforeend', html);
    });
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
const reportSessionSelect = document.getElementById('reportSessionSelect');

async function initReportsDashboard() {
    reportSessionSelect.innerHTML = '<option value="">-- Loading Sessions... --</option>';
    document.getElementById('reportEmptyState').classList.remove('hidden');
    document.getElementById('reportContentArea').classList.add('hidden');
    
    try {
        const res = await fetch('/api/sessions');
        const sessions = await res.json();
        
        reportSessionSelect.innerHTML = '<option value="">-- Select an Executed Session --</option>';
        sessions.forEach(s => {
            if (s.state === 'EXECUTED') {
                const opt = document.createElement('option');
                opt.value = s.session_id;
                opt.innerText = `${s.feature} (${new Date(s.timestamp*1000).toLocaleString()})`;
                reportSessionSelect.appendChild(opt);
            }
        });
    } catch(err) {
        reportSessionSelect.innerHTML = '<option value="">-- Failed to Load --</option>';
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
const unifiedTextInput = document.getElementById('unifiedTextInput');
const unifiedFileInput = document.getElementById('unifiedFileInput');
const runUnifiedAutoBtn = document.getElementById('runUnifiedAutoBtn');
const unifiedAutoStatus = document.getElementById('unifiedAutoStatus');

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
        automationResultsContainer.innerHTML = `<p style="color:var(--fail)">Failed to parse or run cases: ${err.message}</p>`;
    } finally {
        runUnifiedAutoBtn.disabled = false;
    }
});
