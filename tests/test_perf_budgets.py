"""Phase #5 — Performance budget op handlers.

The handlers all read from the same browser perf snapshot. We mock the driver
to return canned metrics dicts, so these tests verify the dispatch + assertion
boundary logic without needing a real browser.
"""

from unittest.mock import MagicMock

import pytest

from utils.action_engine import execute_plan, ActionContext, known_ops
from utils.models import Action


def make_driver(metrics):
    drv = MagicMock()
    drv.execute_script = MagicMock(return_value=metrics)
    return drv


def test_perf_ops_are_registered():
    ops = set(known_ops())
    for required in [
        "measure_perf",
        "assert_ttfb_under", "assert_fcp_under", "assert_lcp_under",
        "assert_dom_loaded_under", "assert_page_load_under",
        "assert_page_size_under", "assert_resource_count_under",
    ]:
        assert required in ops, f"missing perf op: {required}"


def test_measure_perf_binds_to_named_variable():
    metrics = {"ttfb_ms": 120, "fcp_ms": 800, "lcp_ms": 1200, "transfer_bytes": 234000,
               "resource_count": 18, "dom_loaded_ms": 900, "load_complete_ms": 1400,
               "url": "https://example.com"}
    ctx = ActionContext(driver=make_driver(metrics))
    execute_plan([Action(op="measure_perf", name="home_perf")], ctx, retries=1)
    assert ctx.variables["home_perf"]["lcp_ms"] == 1200
    assert ctx.variables["home_perf"]["transfer_bytes"] == 234000


def test_measure_perf_defaults_to_perf_when_unnamed():
    metrics = {"ttfb_ms": 100, "fcp_ms": 600, "lcp_ms": 800}
    ctx = ActionContext(driver=make_driver(metrics))
    execute_plan([Action(op="measure_perf")], ctx, retries=1)
    assert "perf" in ctx.variables
    assert ctx.variables["perf"]["fcp_ms"] == 600


# ---------- Pass cases ----------

@pytest.mark.parametrize("op,key,metric_value,budget", [
    ("assert_ttfb_under",            "ttfb_ms",          200,    500),
    ("assert_fcp_under",             "fcp_ms",           1500,   1800),
    ("assert_lcp_under",             "lcp_ms",           2200,   2500),
    ("assert_dom_loaded_under",      "dom_loaded_ms",    1100,   2000),
    ("assert_page_load_under",       "load_complete_ms", 1800,   3000),
    ("assert_page_size_under",       "transfer_bytes",   500000, 1500000),
    ("assert_resource_count_under",  "resource_count",   25,     50),
])
def test_perf_assertion_pass(op, key, metric_value, budget):
    ctx = ActionContext(driver=make_driver({key: metric_value}))
    execute_plan([Action(op=op, expected=budget)], ctx, retries=1)


# ---------- Fail cases ----------

@pytest.mark.parametrize("op,key,metric_value,budget", [
    ("assert_ttfb_under",            "ttfb_ms",          900,     500),
    ("assert_fcp_under",             "fcp_ms",           2400,    1800),
    ("assert_lcp_under",             "lcp_ms",           3500,    2500),
    ("assert_page_size_under",       "transfer_bytes",   3_000_000, 1_500_000),
    ("assert_resource_count_under",  "resource_count",   120,     50),
])
def test_perf_assertion_fails_when_budget_exceeded(op, key, metric_value, budget):
    ctx = ActionContext(driver=make_driver({key: metric_value}))
    with pytest.raises(AssertionError, match="exceeds budget"):
        execute_plan([Action(op=op, expected=budget)], ctx, retries=1)


def test_missing_metric_surfaces_clear_error():
    # Driver returns {} — page hasn't recorded any perf entries yet.
    ctx = ActionContext(driver=make_driver({}))
    with pytest.raises(AssertionError, match="not available"):
        execute_plan([Action(op="assert_lcp_under", expected=2500)], ctx, retries=1)


def test_budget_accepts_value_field_too():
    """LLM sometimes puts the budget in 'value' instead of 'expected'."""
    ctx = ActionContext(driver=make_driver({"fcp_ms": 600}))
    execute_plan([Action(op="assert_fcp_under", value=1800)], ctx, retries=1)


def test_budget_required():
    ctx = ActionContext(driver=make_driver({"ttfb_ms": 200}))
    with pytest.raises(ValueError, match="numeric budget"):
        execute_plan([Action(op="assert_ttfb_under")], ctx, retries=1)


def test_driver_execute_script_called_with_the_real_snapshot():
    """Smoke: handler does call driver.execute_script (not a typo)."""
    drv = make_driver({"ttfb_ms": 100})
    ctx = ActionContext(driver=drv)
    execute_plan([Action(op="assert_ttfb_under", expected=500)], ctx, retries=1)
    drv.execute_script.assert_called_once()
    # The script reads navigation timing — sanity check the body shape.
    body = drv.execute_script.call_args.args[0]
    assert "performance.getEntriesByType" in body
    assert "transfer_bytes" in body


def test_full_perf_plan_pass_then_fail():
    """A realistic plan: goto, measure, assert mixed budgets."""
    metrics = {"ttfb_ms": 150, "fcp_ms": 900, "lcp_ms": 4000,
               "transfer_bytes": 800_000, "resource_count": 30,
               "dom_loaded_ms": 1100, "load_complete_ms": 1800}
    drv = make_driver(metrics)
    ctx = ActionContext(driver=drv)
    with pytest.raises(AssertionError, match="assert_lcp_under"):
        execute_plan([
            Action(op="measure_perf", name="home"),
            Action(op="assert_ttfb_under", expected=500),       # passes
            Action(op="assert_fcp_under", expected=1800),       # passes
            Action(op="assert_lcp_under", expected=2500),       # fails — 4000 > 2500
            Action(op="assert_page_size_under", expected=2_000_000),  # would pass but not reached
        ], ctx, retries=1)
    # Captured snapshot still bound from the measure_perf step.
    assert ctx.variables["home"]["lcp_ms"] == 4000
