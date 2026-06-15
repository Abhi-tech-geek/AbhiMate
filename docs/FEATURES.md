# AbhiMate — Features

AbhiMate is a multi-agent AI QA platform. You describe a feature in plain
English, and AI agents generate BDD test cases, run them in a real browser,
and explain every failure. Below is the complete feature list and what each
one does.

---

## Core Workflow

| Feature | What it does |
|---|---|
| **AI test generation** | Type a feature in English/Hinglish → 11 AI agents produce BDD test cases in Gherkin (Given/When/Then) across 5 categories: Positive, Negative, Edge, API, Security. |
| **URL scraping** | Paste a website URL → AbhiMate opens it, reads the DOM, and generates tests against the real form fields and buttons. |
| **Screenshot → tests** | Upload a UI screenshot (or Figma mockup) → a vision LLM looks at it and proposes test cases. |
| **Live execution (SSE)** | Tests run in a real browser and stream results live — cards turn blue (running) → green (pass) / red (fail) / yellow (flaky). |
| **Action Plan engine** | Every test is a typed JSON plan (36 ops), never raw code — safe, structured, and engine-agnostic. |

---

## The 13 Features

### 1. Engine-agnostic execution (Selenium + Playwright)
Tests run on either Selenium or Playwright through a single `BrowserPort`
interface. Switch engines with one env var — the same test suite works on both.

### 2. Auth state save / restore
Log in once, save the session (cookies + localStorage), and reuse it across
tests with `save_auth` / `load_auth`. No repeating login steps in every test.

### 3. Accessibility testing (a11y)
Injects axe-core into the page and checks WCAG A/AA/AAA compliance — missing
alt text, unlabeled buttons, low color contrast, keyboard-nav issues, etc.

### 4. Visual regression
Saves a baseline screenshot, then pixel-compares future runs against it. If the
UI changes beyond a threshold, the test fails and a red-highlighted diff image
is produced. Baselines are isolated per user.

### 5. Performance budgets (Web Vitals)
Asserts on real browser metrics: LCP, FCP, CLS, TTFB, page size, request count,
DOM size. Fails the test if the page is slower/heavier than the budget.

### 6. Screenshot → tests (vision AI)
Generates test cases from an image using a Groq vision model (with a smaller
fallback model). Useful when there's no live URL or you're working from a design.

### 7. Scheduling + Slack notifications
Schedule a suite to run automatically (`every 30m`, `daily 09:00`, etc.). A
background scheduler fires due runs and posts results to Slack as a formatted
Block Kit message.

### 8. Parallel execution
Run many test cases concurrently across multiple browser workers
(1/2/4/8). A round-robin splitter spreads cases evenly; results fan back into
the live stream. Big speed-up for large suites.

### 9. Self-healing locators
Every locator carries a fallback chain. When a fallback wins, it's cached and
promoted to primary for next time — so tests survive small UI changes
automatically.

### 10. Record & replay (Chrome extension)
A Manifest-V3 Chrome extension records your real clicks, typing, and navigation
(passwords skipped), exports a JSON, which AbhiMate imports as a runnable
session.

### 11. Bug ticket creation
Push a failing test straight to Jira / GitHub / Linear as an issue — with the
scenario, error, stack trace, and AI-suggested fix pre-filled.

### 12. AI failure deep-dive
A dedicated agent analyzes a failure with full trace + run history and returns a
root cause, hypothesis, suggested fix, and a confidence score.

### 13. Mobile emulation
Run tests on 9 device presets (iPhone 13, Pixel 7, iPad Pro, etc.) — viewport
and user-agent are emulated. Set a global default or per-test device.

---

## Export & Reporting

| Feature | What it does |
|---|---|
| **Export to real code** | Turn a session's Action Plan into runnable test files — **Playwright (Python)**, **Selenium + pytest**, or **Cypress (JS)** — and download them for your own repo. |
| **Markdown export** | Download a clean `.md` report of a run to paste into PRs, Slack, or Jira. |
| **JUnit XML** | Every run emits a JUnit XML file for CI dashboards. |
| **Run diff** | Compare two runs side by side — see what got fixed, what regressed, what's still failing. |
| **Global insights** | AI analyzes all failures across sessions and surfaces recurring bug patterns + suggestions. |

---

## Platform & Account

| Feature | What it does |
|---|---|
| **Authentication** | Email + password (bcrypt-hashed), signed-cookie sessions, signup/login/logout. |
| **Per-user data isolation** | Every session, baseline, and credential is scoped to its owner — no cross-user access. |
| **5-session quota** | Each account keeps up to 5 saved sessions; delete one to make room. Unlimited runs. |
| **4-zone navigation** | Tests · Runs · Insights · Settings. |
| **Command palette** | `Ctrl/Cmd + K` for quick search and navigation. |
| **Light / dark theme** | Toggle with persisted preference. |
| **Glassmorphism UI** | Animated gradient-mesh background, 3D card tilt, smooth transitions. |

---

## Settings (configurable)

- **Slack** — webhook URL + test message
- **Scheduled runs** — create / enable / disable / delete schedules
- **Visual baselines** — upload, view, delete, promote
- **Device** — global mobile/desktop emulation preset
- **Bug-tracker integrations** — Jira / GitHub / Linear credentials
- **Self-heal cache** — inspect and clear promoted locators

---

## Tech Stack

```
Backend     Python · Flask · SQLite
AI          Groq (Llama 3.3 70B + vision models)
Automation  Selenium · Playwright · Chrome
Frontend    Vanilla JS · glassmorphism UI
Deploy      Docker · Railway · custom domain
Testing     Pytest (450+ tests, CI on Python 3.11 & 3.12)
```

---

## Action Plan operations (36)

```
Navigation   goto, reload, back, forward
Interaction  click, fill, press, select, hover, scroll_to, eval_js
Wait         wait_for, wait_for_url, wait_for_selector, sleep
Assertions   assert_text, assert_visible, assert_hidden, assert_url, assert_value
HTTP / API   http_get, http_post, http_put, http_delete, http_assert_status, assert_json_path
Auth         save_auth, load_auth
A11y         assert_a11y, measure_a11y
Performance  assert_lcp_under, assert_fcp_under, assert_cls_under, assert_ttfb_under,
             assert_page_size_under, assert_resource_count_under
Visual       visual_baseline, assert_visual_match
Device       emulate_device, set_viewport
```

---

*Live: https://abhimate.theabhinavsaxena.in · Code: https://github.com/Abhi-tech-geek/AbhiMate*
