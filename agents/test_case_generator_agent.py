from utils.llm_node import LLMNode
from utils.models import TestCase, GherkinStep
from utils.gherkin import normalize_raw_case, validate_case_quality
from typing import List, Optional
import json


GHERKIN_SYSTEM = (
    "You are a Senior QA Automation Engineer with 10+ years experience in "
    "Selenium and BDD. You write Gherkin scenarios that an automation framework "
    "can execute directly. You never invent locators that were not shown to you."
)

FEW_SHOT_EXAMPLE = """
EXAMPLE (login feature, 1 case shown — you will produce many):
{
  "test_cases": [
    {
      "id": "TC001",
      "type": "Positive",
      "tags": ["@smoke", "@happy"],
      "scenario": "Successful login with valid credentials",
      "description": "Verify a registered user can sign in.",
      "gherkin_steps": [
        {"keyword": "Given", "text": "the user is on the login page"},
        {"keyword": "When", "text": "the user enters valid credentials and submits"},
        {"keyword": "Then", "text": "the dashboard is displayed"}
      ],
      "action_plan": [
        {"op": "goto", "url": "https://example.com/login"},
        {"op": "fill", "locator": {"by": "name", "value": "username",
            "fallbacks": [{"by": "css", "value": "input[type=email]"}]},
         "value": "user@example.com"},
        {"op": "fill", "locator": {"by": "name", "value": "password"}, "value": "Correct1!"},
        {"op": "click", "locator": {"by": "css", "value": "button[type=submit]",
            "fallbacks": [{"by": "text", "value": "Sign in"}]}},
        {"op": "wait_for", "locator": {"by": "id", "value": "dashboard"}, "timeout_ms": 10000},
        {"op": "assert_visible", "locator": {"by": "id", "value": "dashboard"}}
      ],
      "expected": "User reaches the dashboard."
    }
  ]
}
""".strip()


GHERKIN_RULES = """
COVERAGE TARGETS (distribute the {count} cases across these categories):
  - Positive  : happy path(s), 2+ cases
  - Negative  : wrong input, missing data, unauthorized
  - Edge      : boundary values, expiry, max/min length, unicode
  - API       : direct REST checks via http_get / http_post / assert_status / assert_json_path
  - Security  : injection, CSRF, rate-limit, token tampering, info leak

PER-CASE RULES:
  1. Use Given / When / Then / And / But keywords.
  2. 3 to 8 gherkin steps per scenario (human-readable, no code).
  3. Also emit an ``action_plan`` — a list of structured operations the engine will execute.
  4. Every assertable outcome MUST appear as an assert_* op in action_plan.
  5. Use semantic locators in this priority: id > testid > name > role > label > placeholder > css > text > xpath.
  6. Always include at least one explicit wait_for or assert_visible before clicking / asserting.
  7. For each locator provide ``fallbacks`` (1-3 alternates) so the self-heal layer can recover.
  8. Tags use @-prefix, lowercase. Common: @smoke, @regression, @api, @security, @flaky.

ALLOWED ops:
  Navigation : goto, back, forward, reload
  Interaction: click, fill, press, select, hover
  Wait       : wait_for, wait_for_url, sleep
  Assert     : assert_text, assert_visible, assert_hidden, assert_url, assert_value
  Capture    : screenshot, scroll
  HTTP       : http_get, http_post, http_put, http_delete, http_patch
  HTTP assert: assert_status, assert_json_path, assert_header, assert_response_time
  Perf       : measure_perf, assert_ttfb_under, assert_fcp_under, assert_lcp_under,
               assert_dom_loaded_under, assert_page_load_under,
               assert_page_size_under, assert_resource_count_under
  A11y       : assert_a11y, measure_a11y
               Use ``assert_a11y`` AFTER the page loads. Default threshold is
               "serious" — any serious or critical WCAG violation fails the
               test. Set ``expected`` to "critical" (strict), "moderate"
               (looser), or "any" (every violation fails).
                 {{"op": "assert_a11y"}}
                 {{"op": "assert_a11y", "expected": "critical"}}
               ``measure_a11y name="report"`` captures the full report
               without failing — useful for non-blocking audits.
  Device     : emulate_device, set_viewport
               Use ``emulate_device`` to switch a test to a mobile / tablet
               profile (viewport + user agent + touch). Known: Desktop,
               iPhone 13, iPhone 15 Pro Max, iPhone SE, Pixel 5, Pixel 7,
               Galaxy S22, iPad Pro 11, iPad mini.
                 {{"op": "emulate_device", "value": "iPhone 13"}}
                 {{"op": "set_viewport",   "value": "375x667"}}
               Always run emulate_device BEFORE goto so the page loads with
               the right UA + dimensions from the first paint.
  Visual     : visual_baseline, assert_visual_match
               Capture a named UI baseline screenshot, then on later runs
               assert the current screenshot still matches. Use this to
               catch unintended visual regressions (layout shifts, colour
               changes, missing CTAs, broken responsive grid). Pattern:
                 {{"op": "wait_for", "locator": {{"by": "id", "value": "checkout"}}}}
                 {{"op": "visual_baseline",     "value": "checkout_page"}}
                 {{"op": "assert_visual_match", "value": "checkout_page", "expected": 0.98}}
               ``expected`` is a similarity floor in [0,1]; default 0.98.
               Set ``expected`` to "force" on a baseline op to overwrite an
               existing baseline when the UI intentionally changed.
               ALWAYS wait_for a stable element BEFORE the visual op — a
               half-loaded page produces flaky diffs.
  Auth state : save_auth, load_auth
               Use ``save_auth`` AFTER the user is logged in to dump cookies +
               localStorage to a named state. Use ``load_auth`` at the START
               of subsequent scenarios to skip the login flow entirely. Names
               are alphanumeric (letters/digits/._-) — e.g.
               {{"op": "save_auth", "value": "logged_in_user"}}
               {{"op": "load_auth", "value": "logged_in_user"}}

For Perf ops, pass the budget on ``expected`` (number). Examples:
  {{"op": "assert_lcp_under",       "expected": 2500}}     // ms — Web Vitals "good" threshold
  {{"op": "assert_fcp_under",       "expected": 1800}}     // ms
  {{"op": "assert_ttfb_under",      "expected": 800}}      // ms
  {{"op": "assert_page_size_under", "expected": 1500000}}  // bytes — 1.5 MB
  {{"op": "assert_resource_count_under", "expected": 50}}
Always run perf assertions AFTER the page has loaded (wait_for_url or wait_for an element first).

LOCATOR strategies: id, testid, name, role, label, placeholder, css, text, xpath, link_text, partial_link_text

OUTPUT FORMAT (strict JSON, single key "test_cases"):
{{
  "test_cases": [
    {{
      "id": "TC001",
      "type": "Positive|Negative|Edge|API|Security",
      "tags": ["@smoke"],
      "scenario": "short title",
      "description": "1-line summary",
      "gherkin_steps": [
        {{"keyword": "Given|When|Then|And|But", "text": "plain English"}}
      ],
      "action_plan": [
        {{"op": "goto", "url": "https://..."}},
        {{"op": "fill", "locator": {{"by": "id", "value": "email",
            "fallbacks": [{{"by": "name", "value": "email"}}]}},
         "value": "u@x.com"}},
        {{"op": "click", "locator": {{"by": "text", "value": "Submit"}}}},
        {{"op": "assert_visible", "locator": {{"by": "id", "value": "dashboard"}}}}
      ],
      "expected": "expected outcome"
    }}
  ]
}}
""".strip()


class TestCaseGeneratorAgent:
    def __init__(self):
        self.llm = LLMNode()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def generate(
        self,
        feature: str,
        model: Optional[str] = None,
        count: int = 8,
    ) -> List[TestCase]:
        count = max(1, min(int(count or 8), 50))
        print(f"-> Generating {count} test cases via LLM (model={model or 'default'})...")

        prompt = self._build_freeform_prompt(feature, count)
        result_dict = self.llm.query_json(GHERKIN_SYSTEM, prompt, model=model)
        return self._parse_and_validate(result_dict, feature_label=feature)

    def generate_from_screenshot(
        self,
        image_b64: str,
        mime_type: str = "image/png",
        count: int = 5,
        hint: Optional[str] = None,
        model: Optional[str] = None,
    ) -> List[TestCase]:
        """Vision-grounded generation. The LLM inspects the screenshot and
        produces test cases that reference the UI elements actually visible
        (not hallucinated). Locators use ``text`` / ``placeholder`` / ``role``
        strategies that don't require a real DOM.

        ``hint`` is an optional free-text nudge — e.g. "This is the checkout
        page; focus on payment validation."
        """
        count = max(1, min(int(count or 5), 30))
        print(f"-> Generating {count} tests from screenshot (model=vision/{model or 'default'})...")

        hint_block = f"\nUser hint: {hint.strip()}\n" if hint else ""

        prompt = (
            "You are looking at a screenshot of a web application. "
            "First, INVENTORY the visible interactive elements (buttons, "
            "inputs, links, dropdowns) and any visible text labels. "
            "Then produce Gherkin BDD test cases grounded in what you SEE. "
            "Do NOT invent elements that are not visible in the screenshot."
            + hint_block + "\n"
            + GHERKIN_RULES.format(count=count) + "\n\n"
            + "EXTRA RULES for screenshot-driven generation:\n"
            + "  - Locators MUST use one of: text, placeholder, role, label, testid.\n"
            + "    Avoid 'id' / 'name' / 'css' unless you genuinely saw the attribute.\n"
            + "  - For every clickable button or input you cite, use the EXACT "
            + "visible label text where possible.\n"
            + "  - If the screen looks like a particular flow (login, checkout, "
            + "search, settings), tag the cases with @<flow-name>.\n\n"
            + FEW_SHOT_EXAMPLE
        )
        result_dict = self.llm.query_vision_json(
            GHERKIN_SYSTEM, prompt, image_b64=image_b64,
            mime_type=mime_type, model=model,
        )
        return self._parse_and_validate(
            result_dict, feature_label="From screenshot"
        )

    def generate_from_url_dom(
        self,
        url: str,
        dom_data: dict,
        model: Optional[str] = None,
        count: int = 6,
    ) -> List[TestCase]:
        count = max(1, min(int(count or 6), 50))
        print(f"-> Generating {count} URL-grounded tests for {url} (model={model or 'default'})...")

        prompt = self._build_dom_prompt(url, dom_data, count)
        result_dict = self.llm.query_json(GHERKIN_SYSTEM, prompt, model=model)
        return self._parse_and_validate(result_dict, feature_label=f"DOM: {url}")

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------
    def _build_freeform_prompt(self, feature: str, count: int) -> str:
        return (
            f"Feature under test:\n{feature}\n\n"
            f"Produce exactly {count} BDD test cases as Gherkin scenarios.\n\n"
            f"{GHERKIN_RULES.format(count=count)}\n\n"
            f"{FEW_SHOT_EXAMPLE}"
        )

    def _build_dom_prompt(self, url: str, dom_data: dict, count: int) -> str:
        elements = json.dumps(dom_data.get("interactable_elements", []), indent=2)[:8000]
        return (
            f"Target URL: {url}\n"
            f"Page title: {dom_data.get('title', 'Unknown')}\n\n"
            f"Interactable elements actually present on the page (use ONLY these — do not invent locators):\n"
            f"{elements}\n\n"
            f"The driver is already loaded on {url}.\n\n"
            f"Produce exactly {count} BDD test cases as Gherkin scenarios grounded in the elements above.\n\n"
            f"{GHERKIN_RULES.format(count=count)}\n\n"
            f"{FEW_SHOT_EXAMPLE}"
        )

    # ------------------------------------------------------------------
    # Parse + validate
    # ------------------------------------------------------------------
    def _parse_and_validate(self, result_dict: dict, feature_label: str) -> List[TestCase]:
        raw_cases = result_dict.get("test_cases", [])
        validated: List[TestCase] = []

        for index, rc in enumerate(raw_cases):
            try:
                # Normalize raw LLM output into the structured shape (derives
                # selenium_action / steps / gherkin text from gherkin_steps).
                normalized = normalize_raw_case(rc, feature_label=feature_label)
                tc = TestCase(**normalized)
                quality_warnings = validate_case_quality(tc)
                if quality_warnings:
                    print(f"  [{tc.id}] quality warnings: {quality_warnings}")
                validated.append(tc)
            except Exception as e:
                print(f"Validation failed for case index {index}: {e}")

        return validated
