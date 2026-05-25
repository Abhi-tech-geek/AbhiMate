from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any, Union


class GherkinStep(BaseModel):
    """One Given/When/Then step. ``code`` is the executable snippet if any."""
    keyword: Literal["Given", "When", "Then", "And", "But"]
    text: str
    code: Optional[str] = None


# ============================================================
# Phase A — engine-agnostic Action Plan
# ============================================================

LocatorBy = Literal[
    "id", "name", "css", "xpath", "text", "role", "label",
    "placeholder", "testid", "link_text", "partial_link_text",
]


class Locator(BaseModel):
    """How to find an element. Carries an ordered fallback chain so the executor
    can self-heal when the primary selector misses."""
    by: LocatorBy
    value: str
    fallbacks: List["Locator"] = Field(default_factory=list)


# Op vocabulary kept open-ended via str so future backends can add ops without
# requiring a schema migration; the executor enforces what it understands.
ActionOp = str


class Action(BaseModel):
    op: ActionOp = Field(..., description="Operation name, e.g. 'click', 'fill', 'http_get'")
    locator: Optional[Locator] = None
    # ``value`` is the field LLMs sometimes mis-use for both strings and
    # numerics (e.g. expected status codes). Accept the common scalar
    # primitives; downstream code uses str() before send_keys.
    value: Optional[Union[str, int, float, bool]] = Field(
        None, description="Text to fill, key to press, url for goto, etc."
    )
    url: Optional[str] = None
    timeout_ms: Optional[int] = Field(None, description="Override default timeout for this action")
    expected: Optional[Any] = Field(None, description="Expected value/text/status for assert ops")
    json_path: Optional[str] = Field(None, description="JSONPath expression for assert_json_path")
    headers: Optional[Dict[str, str]] = None
    body: Optional[Any] = Field(None, description="JSON body for http_post/put/patch")
    name: Optional[str] = Field(None, description="Bind the result to this variable name")
    description: Optional[str] = Field(None, description="Human-readable label shown in trace")


class ActionResult(BaseModel):
    op: str
    success: bool
    duration_ms: int = 0
    attempts: int = 1
    error: Optional[str] = None
    locator_used: Optional[str] = Field(None, description="Which fallback (if any) actually matched")
    console_logs: List[str] = Field(default_factory=list)


# Allow Locator self-reference (fallbacks: List["Locator"]).
Locator.model_rebuild()


class TestCase(BaseModel):
    __test__ = False  # pytest: not a test class
    id: str = Field(..., description="Unique test case ID, e.g., TC001")
    type: Literal["Positive", "Negative", "Edge", "API", "Security"] = Field(
        ..., description="Category of the test case"
    )
    description: str = Field(..., description="Brief summary of what the test case covers")
    steps: List[str] = Field(..., description="Plain-text step list (legacy display)")

    # --- Gherkin upgrade (Phase 1) ---
    tags: List[str] = Field(default_factory=list, description="Gherkin tags like @smoke @api")
    feature: Optional[str] = Field(None, description="Parent feature title")
    scenario: Optional[str] = Field(None, description="Scenario title (BDD)")
    background: List[GherkinStep] = Field(default_factory=list, description="Shared Background steps")
    gherkin_steps: List[GherkinStep] = Field(
        default_factory=list, description="Structured Gherkin steps with per-step code"
    )
    examples: List[Dict[str, str]] = Field(
        default_factory=list, description="Scenario Outline Examples — list of {col: value} rows"
    )
    gherkin: Optional[str] = Field(None, description="Rendered .feature text snippet for display")

    # Legacy aggregated Selenium code (Phase 0-3 path). Optional now — Phase A
    # generators may emit only action_plan instead.
    selenium_action: str = Field("", description="Aggregated Selenium snippet (legacy)")
    # Engine-agnostic Action Plan (Phase A path).
    action_plan: List[Action] = Field(default_factory=list)
    action_results: List[ActionResult] = Field(default_factory=list)
    expected: str = Field(..., description="Expected outcome")
    status: Optional[str] = Field(
        "Un-Run", description="Execution status: Pass, Fail, Skipped, Blocked, or Un-Run"
    )
    error: Optional[str] = Field(None, description="Exception string if the test fails")
    screenshot: Optional[str] = Field(None, description="Path to screenshot on failure")
    bug_insight: Optional[str] = Field(None, description="AI-generated insight into the failure")
    user_skipped: bool = Field(False, description="User unchecked this case before running")
    known_issue: bool = Field(False, description="User marked failure as a known/accepted issue")
    trace_path: Optional[str] = Field(None, description="Path to JSON trace file (action results + logs)")
    visual_artifacts: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Per-case visual regression artifacts (baseline/actual/diff paths + similarity)",
    )

class ExecutionMetrics(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0

class AnalysisReport(BaseModel):
    metrics: ExecutionMetrics = Field(default_factory=ExecutionMetrics)
    executive_summary: str = Field(..., description="High-level summary of the execution run")
    test_cases: List[TestCase] = Field(default_factory=list, description="The test cases attached to this report")

class User(BaseModel):
    """Public projection of a user account (no password hash)."""
    id: int
    email: str
    display_name: Optional[str] = None
    created_at: float
    last_login_at: Optional[float] = None


class TestSession(BaseModel):
    __test__ = False  # pytest: not a test class
    session_id: str
    user_id: Optional[int] = Field(None, description="Owner. None = legacy/orphan session.")
    feature: str
    state: Literal["GENERATED", "EXECUTED", "ARCHIVED"] = "GENERATED"
    timestamp: float
    test_cases: List[TestCase] = Field(default_factory=list)
    report: Optional[AnalysisReport] = None
