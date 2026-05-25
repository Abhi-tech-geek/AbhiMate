"""Accessibility scanning via axe-core (Feature #3).

axe-core is the industry-standard a11y rules engine (the same one Lighthouse,
Cypress, and Playwright recipes use). We inject it via CDN, wait for it to
load, run the scan, and pull back the structured violations.

Why CDN injection instead of bundling?
- axe-core minified is ~500KB. Bundling bloats the Python install.
- The CDN copy is cached by the browser, so subsequent runs are instant.
- If a target page blocks the CDN via CSP, the helper raises a clear error
  the user can act on (e.g. switch to a self-hosted copy).

Both ports speak the same synchronous JS surface (driver.execute_script /
page.evaluate), so this helper works against Selenium and Playwright with
no engine-specific branches.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


AXE_CDN_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.0/axe.min.js"

# WCAG severity ordering — axe returns these strings on each violation.
_SEVERITY_ORDER = ["minor", "moderate", "serious", "critical"]


def _severity_rank(level: str) -> int:
    """Higher is worse. Unknown levels are treated as the lowest tier."""
    if not level:
        return -1
    try:
        return _SEVERITY_ORDER.index(level.lower())
    except ValueError:
        return -1


def filter_violations(
    violations: List[dict],
    threshold: str = "serious",
) -> List[dict]:
    """Keep only violations at-or-above ``threshold``. ``any`` keeps all."""
    if not violations:
        return []
    if (threshold or "").lower() == "any":
        return list(violations)
    cutoff = _severity_rank(threshold)
    return [v for v in violations if _severity_rank(v.get("impact", "")) >= cutoff]


def _evaluate(ctx, script: str):
    """Engine-agnostic JS eval. Mirrors action_engine._evaluate."""
    if getattr(ctx, "port", None) is not None:
        return ctx.port.evaluate(script)
    if getattr(ctx, "driver", None) is not None:
        return ctx.driver.execute_script(script)
    raise RuntimeError("a11y scan needs a browser context (port or driver)")


# ---------------------------------------------------------------------
# JS payloads — kept as constants so tests can inspect / stub them
# ---------------------------------------------------------------------

INJECT_SCRIPT = f"""
return (function () {{
    if (window.axe) return 'already-loaded';
    var s = document.createElement('script');
    s.src = '{AXE_CDN_URL}';
    s.crossOrigin = 'anonymous';
    document.head.appendChild(s);
    return 'injecting';
}})();
""".strip()

CHECK_READY_SCRIPT = "return (typeof window.axe !== 'undefined');"

START_SCAN_SCRIPT = """
return (function () {
    window.__abhimateAxeResults = null;
    window.__abhimateAxeError = null;
    try {
        axe.run(document, {resultTypes: ['violations', 'passes', 'incomplete']})
           .then(function (r) { window.__abhimateAxeResults = r; })
           .catch(function (e) { window.__abhimateAxeError = String(e); });
        return 'started';
    } catch (e) {
        window.__abhimateAxeError = String(e);
        return 'sync-error';
    }
})();
""".strip()

POLL_SCRIPT = "return [window.__abhimateAxeResults, window.__abhimateAxeError];"


# ---------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------

def run_axe(
    ctx,
    timeout_ms: int = 15_000,
    poll_interval_s: float = 0.25,
) -> Dict[str, Any]:
    """Inject axe-core, run a scan, return the parsed result.

    Result shape (subset of what axe emits):
        {
            "violations": [...],    # WCAG failures
            "passes": [...],
            "incomplete": [...],    # rules axe couldn't auto-determine
            "url": "https://...",
            "testEngine": {"name": "axe-core", "version": "4.10.0"}
        }

    Raises AssertionError on:
    - axe failed to load inside the timeout (CSP block / offline / typo)
    - axe loaded but the scan itself errored
    - the whole operation exceeded the timeout
    """
    deadline = time.monotonic() + (timeout_ms / 1000.0)

    # 1. Inject (idempotent — script is a no-op if axe already loaded).
    _evaluate(ctx, INJECT_SCRIPT)

    # 2. Wait for window.axe to materialise.
    while time.monotonic() < deadline:
        if _evaluate(ctx, CHECK_READY_SCRIPT):
            break
        time.sleep(poll_interval_s)
    else:
        raise AssertionError(
            "axe-core failed to load — page may block the CDN via CSP, "
            f"or no internet. Tried {AXE_CDN_URL}"
        )

    # 3. Kick off the scan.
    start = _evaluate(ctx, START_SCAN_SCRIPT)
    if start == "sync-error":
        # axe was loaded but axe.run() threw synchronously — pull the error.
        err = _evaluate(ctx, "return window.__abhimateAxeError;") or "unknown"
        raise AssertionError(f"axe-core threw at start: {err}")

    # 4. Poll for completion.
    while time.monotonic() < deadline:
        result, error = _evaluate(ctx, POLL_SCRIPT) or [None, None]
        if error:
            raise AssertionError(f"axe-core scan errored: {error}")
        if result is not None:
            return _normalize_result(result)
        time.sleep(poll_interval_s)

    raise AssertionError("axe-core scan timed out before producing a result")


def _normalize_result(raw: Any) -> Dict[str, Any]:
    """Trim what we hand to the user — axe's full result is huge."""
    if not isinstance(raw, dict):
        return {"violations": [], "passes": [], "incomplete": [], "raw": raw}
    return {
        "violations": [_trim_rule(r) for r in (raw.get("violations") or [])],
        "passes": [{"id": r.get("id"), "description": r.get("description")}
                   for r in (raw.get("passes") or [])],
        "incomplete": [_trim_rule(r) for r in (raw.get("incomplete") or [])],
        "url": raw.get("url"),
        "testEngine": raw.get("testEngine"),
        "violation_count": len(raw.get("violations") or []),
    }


def _trim_rule(rule: dict) -> dict:
    """Each axe rule has megabytes of debug info — only keep the actionable bits."""
    if not isinstance(rule, dict):
        return {}
    nodes = rule.get("nodes") or []
    return {
        "id": rule.get("id"),
        "impact": rule.get("impact"),
        "description": rule.get("description"),
        "help": rule.get("help"),
        "helpUrl": rule.get("helpUrl"),
        "tags": rule.get("tags") or [],
        "node_count": len(nodes),
        # Keep the first 3 affected nodes for quick triage; full list is huge.
        "nodes": [{
            "target": n.get("target"),
            "html": (n.get("html") or "")[:200],
            "failureSummary": n.get("failureSummary"),
        } for n in nodes[:3]],
    }


def summarize_violations(violations: List[dict]) -> str:
    """One-line summary suitable for an AssertionError message."""
    if not violations:
        return "no violations"
    by_impact: Dict[str, int] = {}
    for v in violations:
        impact = (v.get("impact") or "unknown").lower()
        by_impact[impact] = by_impact.get(impact, 0) + 1
    order = ["critical", "serious", "moderate", "minor", "unknown"]
    parts = [f"{by_impact[k]} {k}" for k in order if k in by_impact]
    return f"{len(violations)} violation(s): " + ", ".join(parts)
