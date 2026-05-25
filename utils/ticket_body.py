"""Compose ticket title + body for a failed test case.

Both JIRA and Linear accept Markdown for the description (we convert to ADF
for JIRA inside the provider adapter). One canonical Markdown body keeps
this module simple and engine-agnostic.

The composer pulls every signal we already have on the case:
- Error + stack
- Action plan + per-op action results
- AI root-cause insight (RCA agent) if present
- Optional deep-dive report if the route attaches one
- Screenshot path (link only — local file; uploading attachments is v2)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def compose_title(case: Dict[str, Any], session: Dict[str, Any],
                  override: Optional[str] = None) -> str:
    """Build a punchy ticket title. ``override`` wins if provided."""
    if override:
        return override.strip()[:200]
    feat = (session or {}).get("feature") or "AbhiMate run"
    cid = case.get("id") or "TC???"
    desc = (case.get("description") or "").strip()
    head = f"[QA] {cid} failed in '{feat}'"
    if desc:
        head = f"{head} — {desc[:80]}"
    return head[:200]


def compose_body(
    case: Dict[str, Any],
    session: Dict[str, Any],
    deep_dive: Optional[Dict[str, Any]] = None,
) -> str:
    """Return the full Markdown body. Always non-empty so providers don't 400."""
    lines: List[str] = []

    # --- Heading ---
    lines.append(f"## Test failure — {case.get('id')}")
    lines.append("")
    lines.append(f"**Feature:** {(session or {}).get('feature', '(unknown)')}")
    lines.append(f"**Session ID:** `{(session or {}).get('session_id', '')}`")
    if case.get("type"):
        lines.append(f"**Category:** {case['type']}")
    if case.get("description"):
        lines.append(f"**Scenario:** {case['description']}")
    if case.get("expected"):
        lines.append(f"**Expected:** {case['expected']}")
    lines.append("")

    # --- Error ---
    err = case.get("error")
    if err:
        lines.append("### Error")
        lines.append("```")
        lines.append(str(err)[:2000])
        lines.append("```")
        lines.append("")

    # --- AI insight ---
    insight = case.get("bug_insight")
    if insight:
        lines.append("### AI root-cause")
        lines.append("> " + str(insight))
        lines.append("")

    # --- Deep-dive ---
    if deep_dive:
        lines.append("### Deep-dive analysis")
        if deep_dive.get("summary"):
            lines.append(f"**Summary:** {deep_dive['summary']}")
        if deep_dive.get("root_cause"):
            lines.append(f"**Root cause:** {deep_dive['root_cause']}")
        if deep_dive.get("why_now"):
            lines.append(f"**Why now:** {deep_dive['why_now']}")
        if deep_dive.get("pattern"):
            lines.append(f"**Pattern:** {deep_dive['pattern']}")
        if deep_dive.get("suggested_fix"):
            lines.append("")
            lines.append(f"**Suggested fix:** {deep_dive['suggested_fix']}")
        patch = deep_dive.get("suggested_action_plan_patch")
        if patch:
            lines.append("")
            lines.append("**Suggested Action-Plan patch**")
            lines.append("```json")
            lines.append(json.dumps(patch, indent=2))
            lines.append("```")
        if deep_dive.get("confidence"):
            lines.append("")
            lines.append(f"_Confidence: {deep_dive['confidence']}_")
        lines.append("")

    # --- Action plan ---
    plan = case.get("action_plan") or []
    if plan:
        lines.append("### Action plan (what we tried)")
        lines.append("```json")
        lines.append(json.dumps(plan, indent=2))
        lines.append("```")
        lines.append("")

    # --- Action results ---
    results = case.get("action_results") or []
    if results:
        lines.append("### Per-op results")
        lines.append("| # | Op | Status | Duration (ms) | Locator | Attempts | Error |")
        lines.append("|---|---|---|---|---|---|---|")
        for i, r in enumerate(results, start=1):
            status = "PASS" if r.get("success") else "FAIL"
            err_cell = (r.get("error") or "").replace("\n", " ")[:120]
            loc = r.get("locator_used") or ""
            lines.append(
                f"| {i} | `{r.get('op','?')}` | {status} | "
                f"{r.get('duration_ms','?')} | `{loc}` | {r.get('attempts','?')} | "
                f"{err_cell} |"
            )
        lines.append("")

    # --- Screenshot (link only — local path note) ---
    shot = case.get("screenshot")
    if shot:
        lines.append("### Failure screenshot")
        lines.append(f"Saved locally to `{shot}`. (Upload-as-attachment is on the roadmap.)")
        lines.append("")

    # --- Footer ---
    lines.append("---")
    lines.append("_Filed automatically by AbhiMate._")
    return "\n".join(lines)


def compose_all(
    case: Dict[str, Any],
    session: Dict[str, Any],
    title_override: Optional[str] = None,
    deep_dive: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Convenience: title + body in one call."""
    return {
        "title": compose_title(case, session, title_override),
        "body": compose_body(case, session, deep_dive=deep_dive),
    }
