# AbhiMate - Next-Generation AI Testing Architecture

Welcome to **AbhiMate**, an ultra-premium, production-grade **Multi-Agent QA System**. AbhiMate natively replaces tedious manual test construction by utilizing the Groq Llama-3 70B LLM to engineer, orchestrate, and physically execute resilient software automation scripts seamlessly from a dedicated Cyber-QA Dashboard.

---

## 🚀 The Multi-Agent Paradigm

AbhiMate operates on a 4-Tier Agent Architecture. It behaves exactly like a Senior QA team.

1. **The Generator (Agent 1):** You type a functional description (e.g. "Google Search logic") into the Chat interface. This agent intercepts the prompt and extrapolates deep, exhaustive, "pure" step-by-step test cases. It also writes corresponding raw Selenium Python code utilizing dynamic waits (EC.presence_of_element_located) to ensure DOM stability.
2. **The Executor (Agent 2):** Native headless and non-headless browser deployment. When you click `Execute Selenium Automation`, this agent spawns a Chromium instance and isolates the AI-generated code securely. It takes visual error screenshots exactly upon finding DOM desyncs.
3. **The Bug Diagnostics Engine (Agent 3):** If a test fails (e.g., `TimeoutException`, `NoSuchElementException`), this agent reads the raw Stack Trace natively and bounces it back to the LLM to write a plain-English, human-readable deduction of *why* the bug occurred and *where*.
4. **The Telemetry Reporter (Agent 4):** Summarizes the exact metrics of the entire test lifecycle, constructing robust JSON outputs consumed directly into the global dashboard.

---

## 💻 The Cyber-QA Dashboard & SPA Configuration
AbhiMate provides a futuristic, robust Web UI tailored strictly for Software Testers:

- **Single Page Application (SPA):** Instant structural transitions. Swap between generating new Chat runs and viewing Global metrics instantly without reloading your DOM.
- **Session Persistence Tracking:** Modeled after ChatGPT, your left Sidebar permanently arrays every historical run you've ever taken. It natively restores the Chat interface back to the exact snapshot of data when clicked.
- **Global Dashboard / Telemetry Hub:** Automatically queries the backend database endpoints traversing all localized configurations. Calculates your overall passing/failing rates across every automation suite you've deployed!
- **Terminal Theming:** Encoded utilizing specific Matrix-Green and Deep-Black styling alongside Monospaced Typefaces specifically structured for DevOps tracking.

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
# Activate Environment (Unix Core)
source venv/bin/activate

# Fetch Core Dependencies
pip install -r requirements.txt
```

### Environment Security
We utilize local `.env` bindings to keep all external API keys out of root directories.
1. Extract `.env.example` -> Rename to `.env`.
2. Input `GROQ_API_KEY=your_authentication_key`.

---

## 🎯 Boot Sequence & Operation

Initialize the backend architectural wrapper.
```bash
python app.py
```
Open **[http://127.0.0.1:5000](http://127.0.0.1:5000)** inside your browser.

1. **Generation:** Press "+ New Session". Log your target (e.g., `GitHub User Matrix Login`).
2. **Evaluation:** Wait for the AI LLM to construct your Ledger payload.
3. **Execution Decision:** View your metrics and intelligently decide whether to save them passively locally or initialize the Selenium Engine to rip through the DOM natively!

---
*Developed with rigorous stability and structural integrity frameworks.*
