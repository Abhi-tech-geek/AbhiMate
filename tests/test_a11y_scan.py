"""Feature #3 — axe-core a11y scanning.

We don't run a real browser here. ``port.evaluate`` is mocked so we return
canned axe results, then verify the helper + action handlers do the right
thing with them.
"""

from unittest.mock import MagicMock

import pytest

from utils.action_engine import execute_plan, ActionContext, known_ops
from utils.models import Action
from utils.a11y import (
    filter_violations, summarize_violations, run_axe,
    INJECT_SCRIPT, CHECK_READY_SCRIPT, START_SCAN_SCRIPT, POLL_SCRIPT,
    AXE_CDN_URL,
)


# ---------------------------------------------------------------------
# Helpers — fake port that scripts its JS responses
# ---------------------------------------------------------------------

def make_axe_result(violations=None, passes=None, incomplete=None):
    return {
        "violations": violations or [],
        "passes": passes or [],
        "incomplete": incomplete or [],
        "url": "https://example.com/",
        "testEngine": {"name": "axe-core", "version": "4.10.0"},
    }


def violation(rule_id, impact, nodes=1):
    return {
        "id": rule_id,
        "impact": impact,
        "description": f"{rule_id} description",
        "help": f"Fix {rule_id}",
        "helpUrl": f"https://dequeuniversity.com/rules/axe/{rule_id}",
        "tags": ["wcag2a"],
        "nodes": [{"target": ["#x"], "html": f"<el id=\"x\">{i}</el>",
                   "failureSummary": "Fix it"} for i in range(nodes)],
    }


class _ScriptedPort:
    """Returns canned values for each scripted JS call, in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.driver = None

    def evaluate(self, script):
        self.calls.append(script)
        if not self.responses:
            raise RuntimeError("Test: ran out of scripted axe responses")
        return self.responses.pop(0)


# ---------------------------------------------------------------------
# filter_violations / summarize_violations
# ---------------------------------------------------------------------

@pytest.mark.parametrize("threshold,kept", [
    ("critical", ["color-contrast"]),
    ("serious",  ["color-contrast", "label"]),
    ("moderate", ["color-contrast", "label", "region"]),
    ("minor",    ["color-contrast", "label", "region", "alt-text-min"]),
    ("any",      ["color-contrast", "label", "region", "alt-text-min"]),
])
def test_filter_violations_by_threshold(threshold, kept):
    vios = [
        violation("color-contrast", "critical"),
        violation("label", "serious"),
        violation("region", "moderate"),
        violation("alt-text-min", "minor"),
    ]
    out = filter_violations(vios, threshold=threshold)
    assert [v["id"] for v in out] == kept


def test_filter_violations_empty():
    assert filter_violations([], threshold="serious") == []
    assert filter_violations([], threshold="any") == []


def test_summarize_violations_counts_by_impact():
    vios = [
        violation("a", "critical"),
        violation("b", "critical"),
        violation("c", "serious"),
        violation("d", "minor"),
    ]
    s = summarize_violations(vios)
    assert "4 violation(s)" in s
    assert "2 critical" in s
    assert "1 serious" in s
    assert "1 minor" in s


def test_summarize_violations_empty():
    assert summarize_violations([]) == "no violations"


# ---------------------------------------------------------------------
# run_axe — the polling state machine
# ---------------------------------------------------------------------

def test_run_axe_happy_path():
    port = _ScriptedPort([
        "injecting",                                  # INJECT
        True,                                          # CHECK_READY
        "started",                                     # START_SCAN
        [make_axe_result(violations=[violation("x", "serious")]), None],  # POLL
    ])
    ctx = ActionContext(port=port)
    result = run_axe(ctx, timeout_ms=2000)
    assert result["violation_count"] == 1
    assert result["violations"][0]["id"] == "x"


def test_run_axe_axe_already_loaded():
    """If axe is already on the page, we still poll for ready then run."""
    port = _ScriptedPort([
        "already-loaded",                              # INJECT (no-op)
        True,                                           # CHECK_READY
        "started",                                      # START_SCAN
        [make_axe_result(), None],                      # POLL (clean)
    ])
    ctx = ActionContext(port=port)
    result = run_axe(ctx, timeout_ms=2000)
    assert result["violation_count"] == 0


def test_run_axe_load_timeout_raises_clearly():
    """axe never loads — we should get an actionable error mentioning CSP."""
    port = _ScriptedPort([
        "injecting",
        # CHECK_READY always returns False until timeout
    ] + [False] * 30)
    ctx = ActionContext(port=port)
    with pytest.raises(AssertionError, match="axe-core failed to load"):
        run_axe(ctx, timeout_ms=300, poll_interval_s=0.05)


def test_run_axe_scan_errors_propagate():
    port = _ScriptedPort([
        "injecting",
        True,
        "started",
        [None, "TypeError: cannot read undefined"],
    ])
    ctx = ActionContext(port=port)
    with pytest.raises(AssertionError, match="scan errored"):
        run_axe(ctx, timeout_ms=2000)


def test_run_axe_sync_error_at_start():
    port = _ScriptedPort([
        "injecting",
        True,
        "sync-error",
        "ReferenceError: axe.run is not a function",
    ])
    ctx = ActionContext(port=port)
    with pytest.raises(AssertionError, match="threw at start"):
        run_axe(ctx, timeout_ms=2000)


def test_run_axe_normalizes_huge_node_lists():
    """axe can return many nodes per rule — we keep only the first 3."""
    rule = violation("color-contrast", "critical", nodes=12)
    port = _ScriptedPort([
        "injecting", True, "started",
        [make_axe_result(violations=[rule]), None],
    ])
    ctx = ActionContext(port=port)
    out = run_axe(ctx, timeout_ms=2000)
    v = out["violations"][0]
    assert v["node_count"] == 12
    assert len(v["nodes"]) == 3   # trimmed


def test_run_axe_uses_correct_cdn_url():
    """The injection script should embed our chosen CDN url."""
    assert AXE_CDN_URL in INJECT_SCRIPT


def test_script_constants_are_self_contained():
    """Each script should be runnable as-is by execute_script."""
    for s in [INJECT_SCRIPT, CHECK_READY_SCRIPT, START_SCAN_SCRIPT, POLL_SCRIPT]:
        assert "return " in s


# ---------------------------------------------------------------------
# assert_a11y action op
# ---------------------------------------------------------------------

def test_assert_a11y_ops_registered():
    assert "assert_a11y" in known_ops()
    assert "measure_a11y" in known_ops()


def test_assert_a11y_passes_when_no_violations():
    port = _ScriptedPort([
        "injecting", True, "started",
        [make_axe_result(violations=[]), None],
    ])
    ctx = ActionContext(port=port)
    execute_plan([Action(op="assert_a11y")], ctx, retries=1)


def test_assert_a11y_passes_when_below_threshold():
    """Default threshold is 'serious' — minor violations should not fail."""
    port = _ScriptedPort([
        "injecting", True, "started",
        [make_axe_result(violations=[violation("alt", "minor")]), None],
    ])
    ctx = ActionContext(port=port)
    execute_plan([Action(op="assert_a11y")], ctx, retries=1)


def test_assert_a11y_fails_on_serious_violation():
    port = _ScriptedPort([
        "injecting", True, "started",
        [make_axe_result(violations=[violation("label", "serious")]), None],
    ])
    ctx = ActionContext(port=port)
    with pytest.raises(AssertionError, match="assert_a11y"):
        execute_plan([Action(op="assert_a11y")], ctx, retries=1)


def test_assert_a11y_critical_threshold_ignores_serious():
    """expected=critical means serious + below all pass."""
    port = _ScriptedPort([
        "injecting", True, "started",
        [make_axe_result(violations=[violation("label", "serious")]), None],
    ])
    ctx = ActionContext(port=port)
    execute_plan([Action(op="assert_a11y", expected="critical")], ctx, retries=1)


def test_assert_a11y_any_threshold_fails_on_minor():
    port = _ScriptedPort([
        "injecting", True, "started",
        [make_axe_result(violations=[violation("alt", "minor")]), None],
    ])
    ctx = ActionContext(port=port)
    with pytest.raises(AssertionError, match="assert_a11y"):
        execute_plan([Action(op="assert_a11y", expected="any")], ctx, retries=1)


def test_assert_a11y_value_field_also_works():
    """LLM sometimes puts threshold in 'value' instead of 'expected'."""
    port = _ScriptedPort([
        "injecting", True, "started",
        [make_axe_result(violations=[violation("label", "serious")]), None],
    ])
    ctx = ActionContext(port=port)
    execute_plan([Action(op="assert_a11y", value="critical")], ctx, retries=1)


def test_assert_a11y_binds_report_when_named():
    port = _ScriptedPort([
        "injecting", True, "started",
        [make_axe_result(violations=[violation("alt", "minor")]), None],
    ])
    ctx = ActionContext(port=port)
    execute_plan([Action(op="assert_a11y", name="home_a11y")], ctx, retries=1)
    assert "home_a11y" in ctx.variables
    assert ctx.variables["home_a11y"]["violation_count"] == 1


def test_assert_a11y_error_message_names_the_worst_violation():
    port = _ScriptedPort([
        "injecting", True, "started",
        [make_axe_result(violations=[
            violation("label", "serious"),
            violation("color-contrast", "critical"),
            violation("region", "moderate"),
        ]), None],
    ])
    ctx = ActionContext(port=port)
    with pytest.raises(AssertionError) as exc:
        execute_plan([Action(op="assert_a11y")], ctx, retries=1)
    # Worst impact (critical) should be in the message
    assert "color-contrast" in str(exc.value)
    assert "critical" in str(exc.value)


# ---------------------------------------------------------------------
# measure_a11y action op
# ---------------------------------------------------------------------

def test_measure_a11y_never_raises_on_violations():
    """measure_a11y captures the report without failing the test."""
    port = _ScriptedPort([
        "injecting", True, "started",
        [make_axe_result(violations=[violation("label", "critical")]), None],
    ])
    ctx = ActionContext(port=port)
    execute_plan([Action(op="measure_a11y", name="report")], ctx, retries=1)
    assert ctx.variables["report"]["violation_count"] == 1


def test_measure_a11y_default_name():
    port = _ScriptedPort([
        "injecting", True, "started",
        [make_axe_result(), None],
    ])
    ctx = ActionContext(port=port)
    execute_plan([Action(op="measure_a11y")], ctx, retries=1)
    assert "a11y" in ctx.variables


def test_measure_a11y_still_raises_on_infra_error():
    """If axe itself fails to load, measure_a11y can't return a report."""
    port = _ScriptedPort([
        "injecting",
    ] + [False] * 30)
    ctx = ActionContext(port=port)
    with pytest.raises(AssertionError):
        execute_plan([Action(op="measure_a11y", timeout_ms=200)], ctx, retries=1)


# ---------------------------------------------------------------------
# Realistic mixed plan
# ---------------------------------------------------------------------

def test_a11y_after_goto_in_a_plan():
    """A typical plan: goto, wait, assert_a11y."""
    class FullPort(_ScriptedPort):
        def __init__(self, responses):
            super().__init__(responses)
            self.nav = []
        def goto(self, url): self.nav.append(url)
        @property
        def current_url(self): return "https://example.com/"
        def find(self, locator, ms):
            class _El:
                def is_displayed(self): return True
                @property
                def text(self): return ""
            return _El(), f"{locator.by}={locator.value}"

    port = FullPort([
        "injecting", True, "started",
        [make_axe_result(), None],
    ])
    from utils.models import Locator
    ctx = ActionContext(port=port)
    execute_plan([
        Action(op="goto", url="https://example.com/"),
        Action(op="wait_for", locator=Locator(by="css", value="main")),
        Action(op="assert_a11y"),
    ], ctx, retries=1)
    assert port.nav == ["https://example.com/"]
