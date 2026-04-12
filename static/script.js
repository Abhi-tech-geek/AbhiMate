let currentSessionId = null;

// DOM Elements
const newSessionBtn = document.getElementById('newSessionBtn');
const historyList = document.getElementById('historyList');
const promptInput = document.getElementById('promptInput');
const sendPromptBtn = document.getElementById('sendPromptBtn');
const welcomeSplash = document.getElementById('welcomeSplash');
const messagesContainer = document.getElementById('messagesContainer');
const sessionFeatureText = document.getElementById('sessionFeatureText');
const testCasesContainer = document.getElementById('testCasesContainer');
const automationActionArea = document.getElementById('automationActionArea');
const triggerAutomationBtn = document.getElementById('triggerAutomationBtn');
const saveManualBtn = document.getElementById('saveManualBtn');
const executionResultsArea = document.getElementById('executionResultsArea');

document.addEventListener('DOMContentLoaded', loadSessions);

newSessionBtn.addEventListener('click', resetChat);

// Allow pressing Enter to send prompt
promptInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendGenerateRequest();
    }
});

sendPromptBtn.addEventListener('click', sendGenerateRequest);

triggerAutomationBtn.addEventListener('click', sendExecuteRequest);
saveManualBtn.addEventListener('click', () => {
    automationActionArea.innerHTML = "<p>✅ Test Cases saved manually in standard history. Automation skipped.</p>";
});

async function loadSessions() {
    try {
        const res = await fetch('/api/sessions');
        const sessions = await res.json();
        historyList.innerHTML = '';
        sessions.forEach(s => {
            const li = document.createElement('li');
            li.className = 'history-item';
            li.innerText = s.feature;
            li.onclick = () => loadSessionData(s.id);
            historyList.appendChild(li);
        });
    } catch (err) {
        console.error("Failed to load sessions", err);
    }
}

function resetChat() {
    currentSessionId = null;
    promptInput.value = '';
    welcomeSplash.classList.remove('hidden');
    messagesContainer.classList.add('hidden');
    testCasesContainer.innerHTML = '';
    automationActionArea.classList.add('hidden');
    executionResultsArea.classList.add('hidden');
    
    // reset history active state
    document.querySelectorAll('.history-item').forEach(el => el.classList.remove('active'));
}

async function loadSessionData(sessionId) {
    resetChat();
    currentSessionId = sessionId;
    
    welcomeSplash.classList.add('hidden');
    messagesContainer.classList.remove('hidden');
    
    // Skeleton loader
    sessionFeatureText.innerHTML = "Loading history...";
    testCasesContainer.innerHTML = '<div class="loading-skeleton"></div><div class="loading-skeleton"></div>';
    
    try {
        const res = await fetch(`/api/sessions/${sessionId}`);
        const data = await res.json();
        
        sessionFeatureText.innerText = data.feature;
        promptInput.value = data.feature;
        
        renderTestCases(data.test_cases || []);
        
        if (data.state === "EXECUTED") {
            // Render execution results
            automationActionArea.classList.add('hidden');
            renderExecutionMetrics(data);
        } else {
            // Show prompt to automate
            automationActionArea.classList.remove('hidden');
            executionResultsArea.classList.add('hidden');
        }
        
    } catch (err) {
        sessionFeatureText.innerText = "Error loading session!";
    }
}

async function sendGenerateRequest() {
    const text = promptInput.value.trim();
    if (!text) return;
    
    resetChat();
    promptInput.value = text;
    
    welcomeSplash.classList.add('hidden');
    messagesContainer.classList.remove('hidden');
    
    sessionFeatureText.innerText = text;
    testCasesContainer.innerHTML = `
        <div class="loading-skeleton"></div>
        <div class="loading-skeleton"></div>
        <div class="loading-skeleton"></div>
        <p style="color:var(--text-secondary); text-align:center;">AbhiMate is engineering exhaustive test logic...</p>
    `;
    
    sendPromptBtn.disabled = true;

    try {
        const res = await fetch('/api/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ feature: text })
        });
        const data = await res.json();
        
        if (!res.ok) throw new Error(data.error);
        
        currentSessionId = data.session_id;
        renderTestCases(data.test_cases);
        automationActionArea.classList.remove('hidden');
        
        loadSessions(); // Reload sidebar
        
    } catch (err) {
        testCasesContainer.innerHTML = `<p style="color:#ef4444">${err.message}</p>`;
    } finally {
        sendPromptBtn.disabled = false;
    }
}

async function sendExecuteRequest() {
    if (!currentSessionId) return;
    
    triggerAutomationBtn.disabled = true;
    triggerAutomationBtn.innerText = "Running Agents in Background...";
    
    try {
        const res = await fetch(`/api/execute/${currentSessionId}`, {
            method: 'POST'
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);
        
        automationActionArea.classList.add('hidden');
        
        // Re-render test cases to show pass/fail tags
        renderTestCases(data.test_cases);
        renderExecutionMetrics(data);
        
    } catch (err) {
        alert(err.message);
    } finally {
        triggerAutomationBtn.disabled = false;
        triggerAutomationBtn.innerText = "🚀 Execute Selenium Automation";
    }
}

function renderTestCases(cases) {
    testCasesContainer.innerHTML = '';
    cases.forEach(tc => {
        const status = tc.status || "Un-Run";
        const statusClass = `status-${status.toLowerCase()}`;
        
        let insightMarkup = '';
        if (status === 'Fail' && tc.bug_insight) {
            insightMarkup = `
                <div class="tc-insight">
                    <strong>🐞 Bug Analyzer Agent:</strong>
                    ${tc.bug_insight}
                </div>
            `;
        }

        const tcHTML = `
            <div class="tc-card">
                <div class="tc-header">
                    <span class="tc-id">${tc.id} - ${tc.type}</span>
                    <span class="badge ${statusClass}">${status}</span>
                </div>
                <div class="tc-desc" style="white-space: pre-wrap; font-family: monospace; background:rgba(0,0,0,0.2); padding:10px; border-radius:6px; margin-bottom:10px;">${tc.description}
${(tc.steps || []).join('\n')}
                </div>
                <div><strong>Expected:</strong> ${tc.expected}</div>
                ${insightMarkup}
            </div>
        `;
        testCasesContainer.insertAdjacentHTML('beforeend', tcHTML);
    });
}

function renderExecutionMetrics(data) {
    executionResultsArea.classList.remove('hidden');
    if (data.metrics) {
        document.getElementById('metricTotal').innerText = data.metrics.total;
        document.getElementById('metricPassed').innerText = data.metrics.passed;
        document.getElementById('metricFailed').innerText = data.metrics.failed;
    }
    if (data.executive_summary) {
        document.getElementById('executiveSummary').innerText = data.executive_summary;
    }
}
