# AbhiMate - Next-Generation AI Testing Architecture

Welcome to **AbhiMate**, an ultra-premium, production-grade **Multi-Agent QA System**. AbhiMate natively replaces tedious manual test construction by utilizing advanced LLMs to engineer, orchestrate, and physically execute resilient software automation scripts seamlessly from a dedicated Cyber-QA Dashboard.

---

## 🚀 The Multi-Agent Paradigm

AbhiMate has undergone a major core architectural redesign. It operates on a strict 4-Tier Agent Architecture using typed Pydantic structures. It behaves exactly like a senior QA team:

1. **`TestCaseGeneratorAgent` (Agent 1):** You type a functional description (e.g. "Google Search logic") into the Chat interface. This agent intercepts the prompt and extrapolates deep, exhaustive step-by-step test cases. It also generates corresponding raw Selenium Python code.
2. **`AutomationExecutorAgent` (Agent 2):** Engineered with a robust driver abstraction layer. This agent spawns a Chromium instance and isolates the AI-generated python code securely. It takes visual error screenshots exactly upon finding DOM desyncs. Ready for future Android integrations.
3. **`ReportAndAnalysisAgent` (Agent 3):** If a test fails, this agent reads the raw Stack Trace natively and bounces it back to the LLM to write a plain-English, human-readable deduction of *why* the bug occurred and packages it into an Executive Analysis Report.
4. **`MemoryManagerAgent` (Agent 4):** Central nervous system of the platform. Interacts with a SQLite database backend to guarantee absolute data persistence for test sessions, metrics, and workflows.

---

## 💻 The Cyber-QA Dashboard Configuration

AbhiMate provides a futuristic, robust Web UI tailored strictly for Software Testers:

- **Single Page Application (SPA):** Top Navigation Bar isolating Dashboards from Global Reporting. Swap between workflows effortlessly.
- **Session Persistence Tracking:** Modeled after ChatGPT, your left Sidebar strictly contains your historical session logs.
- **Global AI Infographics:** Visualize overarching success metrics directly mapped with Chart.js. Generative AI scans across every historical failure globally to deliver executive Bug Pattern suggestions dynamically.
- **Zero-Touch Automation Pipeline:** Bypass the Human-in-the-loop requirement! Write your feature and let the AI generate the JSON suite, fire up Selenium, and compile the final report back-to-back synchronously.
- **URL Auto Testing:** Full automation. Enter a raw server URL, and the core Headless driver natively scrapes and maps the internal DOM to generate perfectly mapped Selenium models, executing them instantaneously.
- **Direct JSON Runner:** Empower engineers who already have test case arrays to bypass generative steps natively, passing existing models directly into the Executor node.

---

## 📦 System Installation

### Prerequisites
Ensure you have **Python 3.10+** and Git installed locally on your network frame. 
You will also require a valid `GROQ_API_KEY`.

### Initialization
```bash
# Clone the repository
git clone https://github.com/Abhi-tech-geek/AbhiMate.git
cd AbhiMate

# Deploy an isolated Environment 
python -m venv venv

# Activate Environment (Windows Core)
venv\Scripts\activate

# Fetch Core Dependencies
pip install -r requirements.txt
```

### Environment Security
We utilize local `.env` bindings to keep all external API keys out of root directories.
1. Extract `.env.example` -> Rename to `.env`.
2. Input `GROQ_API_KEY=your_authentication_key`.

---

## 🎯 Boot Sequence & Operation

Initialize the backend REST Flask architectural wrapper.
```bash
python app.py
```
Open **[http://127.0.0.1:5000](http://127.0.0.1:5000)** inside your browser.

1. **Generation:** Press "+ New Session". Log your target.
2. **Human in the Loop:** Wait for the AI LLM to construct your test payload. Intelligently decide whether to edit it passively or initialize the Selenium Engine to execute it!
3. **Automated Substation:** Switch to the 'Automated' tab to test out Zero-Touch executions without workflow interruptions.

---
*Developed with rigorous stability and structural integrity frameworks.*
