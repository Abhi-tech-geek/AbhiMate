# AbhiMate Architecture

## Pipeline
```
User prompt
    │
    ▼
MultiLanguageAgent  (Hinglish → English adapt)
    │
    ▼
URL detected? ──── yes ──► WebSeleniumDriver.extract_dom_map ──► FormUnderstandingAgent ──► generate_from_url_dom
    │                                                                                              │
    no                                                                                             │
    ▼                                                                                              ▼
TestCaseGeneratorAgent.generate ─────────────────────────────────────────────────► [List[TestCase]]
                                                                                              │
                                                                                              ▼ (autoRun)
                                                                                  AutomationExecutorAgent
                                                                                              │
                                                                                              ▼
                                                                                  RootCauseAnalyzerAgent (per failure)
                                                                                              │
                                                                                              ▼
                                                                                  PerformanceTestingAgent
                                                                                              │
                                                                                              ▼
                                                                                  ReportAndAnalysisAgent
                                                                                              │
                                                                                              ▼
                                                                                  MemoryManagerAgent ─► SQLite
```

## Folder layout
```
Abhimate/
├── app.py                    Flask entrypoint
├── agents/                   10 agent classes
├── utils/
│   ├── models.py             Pydantic schemas
│   ├── llm_node.py           Groq client wrapper
│   └── automation_drivers.py Selenium driver abstraction
├── database/
│   ├── db_core.py            SQLite helper
│   └── abhimate.db           Live DB file
├── prompt_templates/         Externalized prompts
├── ui/
│   ├── templates/index.html
│   └── static/{script.js, style.css}
├── data/
│   ├── sessions/             Legacy/exported JSON snapshots
│   └── screenshots/          Failure captures per session_id
├── tests/                    Pytest suite (scaffold)
└── docs/                     This folder
```

## Agent responsibilities
| Agent | Role | Status |
|---|---|---|
| TestCaseGeneratorAgent | Prompt → JSON test array | active |
| AutomationExecutorAgent | Run Selenium code → metrics | active |
| ReportAndAnalysisAgent | LLM exec summary + global insights | active |
| MemoryManagerAgent | SQLite persistence | active |
| FormUnderstandingAgent | DOM map → key form fields | active |
| RootCauseAnalyzerAgent | Stacktrace → human RC | active |
| PerformanceTestingAgent | Timing buckets | active |
| MultiLanguageAgent | Hinglish/Hindi → English | active (always fires — optimize) |
| DataDrivenTestingAgent | CSV → variants | half-wired (parse only) |
| ModelSelectorAgent | Pick Groq model | **unused** (wire to LLMNode) |
| ReportingAgent | Alt report shape | **unused** (dead code) |
