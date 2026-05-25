"""DeepDiveAgent — richer per-failure diagnosis (Feature #12).

This is the heavier sibling of RootCauseAnalyzerAgent. RCA gives a 1-2
sentence quick read. DeepDive packages every signal we have — action
results, console logs, prior failure history, locator-cache evidence — and
asks the LLM for a structured multi-paragraph diagnosis that a developer
can act on without opening DevTools.

Output JSON shape:
    {
        "summary":         "one-sentence headline",
        "root_cause":      "what went wrong, technically",
        "why_now":         "what changed (DOM, timing, auth, network) to trigger this",
        "pattern":         "is this a known-recurring issue, or first time?",
        "suggested_fix":   "code-level fix the dev can apply",
        "suggested_action_plan_patch": <Action JSON the user can paste>,
        "confidence":      "low | medium | high"
    }
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from utils.llm_node import LLMNode


SYSTEM_MESSAGE = (
    "You are a senior QA debugging engineer. Given a failed Selenium / "
    "Playwright test and rich runtime context, produce a careful, "
    "developer-facing diagnosis. Always reply with strict JSON in the shape "
    "the user shows you. Be concrete and cite the action step or console "
    "log line that supports each claim."
)


class DeepDiveAgent:
    def __init__(self):
        self.llm = LLMNode()

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------

    def analyze(
        self,
        test_case_dict: Dict[str, Any],
        context: Dict[str, Any],
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the deep-dive prompt. ``context`` is built by
        ``gather_deep_dive_context`` and includes console logs, prior
        history, and a locator-cache snapshot."""
        prompt = self._build_prompt(test_case_dict, context)
        try:
            result = self.llm.query_json(SYSTEM_MESSAGE, prompt, model=model)
        except Exception as e:  # noqa: BLE001
            return {
                "summary": "Deep dive unavailable — LLM call failed.",
                "root_cause": str(e)[:300],
                "why_now": "",
                "pattern": "",
                "suggested_fix": "",
                "suggested_action_plan_patch": None,
                "confidence": "low",
            }
        return self._normalize(result)

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    def _build_prompt(self, tc: Dict[str, Any], context: Dict[str, Any]) -> str:
        prior = context.get("prior_runs") or []
        prior_summary = (
            "First time we have seen this case fail."
            if not prior
            else f"Past failures of same case_id ({len(prior)} prior): "
                 + "; ".join(
                     f"{p.get('feature','?')} at {p.get('timestamp','?')}: {p.get('error','')[:80]}"
                     for p in prior[:5]
                 )
        )

        action_summary = _format_action_results(tc.get("action_results") or [])
        plan_summary = _format_action_plan(tc.get("action_plan") or [])
        console = context.get("console_logs") or []
        console_summary = (
            "No console logs captured."
            if not console
            else "\n".join(
                f"  [{(c.get('level') or 'INFO').upper()}] {(c.get('message') or '')[:200]}"
                for c in console[:20]
            )
        )

        cache_snapshot = context.get("locator_cache") or []
        cache_summary = (
            "No locator-cache hints on this host."
            if not cache_snapshot
            else "\n".join(
                f"  ({c.get('primary_by')}={c.get('primary_value')}) -> "
                f"({c.get('winning_by')}={c.get('winning_value')}) "
                f"used {c.get('success_count', 0)}x"
                for c in cache_snapshot[:10]
            )
        )

        return f"""
A test case just failed. Here is everything I know about the run.

TEST CASE
=========
ID:            {tc.get('id')}
Type:          {tc.get('type')}
Description:   {tc.get('description')}
Expected:      {tc.get('expected')}
Status:        {tc.get('status')}
Error:         {tc.get('error')}
Prior insight: {tc.get('bug_insight') or '(none)'}

ACTION PLAN (the JSON list the engine tried to execute)
=======================================================
{plan_summary}

ACTION RESULTS (per-op timing + winning locator)
================================================
{action_summary}

BROWSER CONSOLE LOGS (most recent 20)
=====================================
{console_summary}

LOCATOR-CACHE HINTS (what previously-winning selectors we have for this host)
============================================================================
{cache_summary}

PRIOR HISTORY OF THIS CASE
==========================
{prior_summary}

OUTPUT (strict JSON — no markdown)
==================================
Respond with ONLY this JSON object, no preamble:
{{
  "summary":         "one-sentence headline a manager would understand",
  "root_cause":      "technical explanation citing the failing action and any console errors",
  "why_now":         "what changed (DOM, timing, auth, CSP, network) — be concrete",
  "pattern":         "is this a recurring flake or first-time bug? base on PRIOR HISTORY above",
  "suggested_fix":   "developer-actionable fix — describe locator change, wait change, or auth change",
  "suggested_action_plan_patch": {{ "op": "...", "locator": {{ ... }} }} OR null,
  "confidence":      "high | medium | low — pick one based on signal strength"
}}
""".strip()

    # ------------------------------------------------------------------
    # Defense — LLM sometimes drops fields
    # ------------------------------------------------------------------

    def _normalize(self, result: Dict[str, Any]) -> Dict[str, Any]:
        out = {
            "summary": "",
            "root_cause": "",
            "why_now": "",
            "pattern": "",
            "suggested_fix": "",
            "suggested_action_plan_patch": None,
            "confidence": "low",
        }
        if isinstance(result, dict):
            for k in out:
                if k in result and result[k] is not None:
                    out[k] = result[k]
            # Clamp confidence to allowed values
            conf = str(out["confidence"]).strip().lower()
            out["confidence"] = conf if conf in {"low", "medium", "high"} else "low"
        return out


# =====================================================================
# Context gatherer — pure function for testability
# =====================================================================

def gather_deep_dive_context(
    session: Any,
    case_id: str,
    db,
    traces_dir: str = "data/traces",
) -> Dict[str, Any]:
    """Build the context blob passed to ``DeepDiveAgent.analyze``.

    All inputs are optional — missing pieces are returned as empty defaults
    so the LLM still gets a structured prompt, just less rich.
    """
    out: Dict[str, Any] = {
        "console_logs": [],
        "prior_runs": [],
        "locator_cache": [],
    }

    # 1. Console logs from the per-case trace file (Phase A artifact).
    sid = getattr(session, "session_id", None) or (session.get("session_id") if isinstance(session, dict) else None)
    if sid:
        trace_path = os.path.join(traces_dir, str(sid), f"{case_id}.json")
        if os.path.isfile(trace_path):
            try:
                with open(trace_path, "r", encoding="utf-8") as f:
                    trace = json.load(f) or {}
                out["console_logs"] = trace.get("console_logs") or []
            except Exception:
                pass

    # 2. Locator-cache hints for the host. Best-effort — we may not be able
    #    to derive a host without the action plan; pull a few recent rows.
    if db is not None and hasattr(db, "list_locator_cache"):
        try:
            out["locator_cache"] = db.list_locator_cache(limit=10) or []
        except Exception:
            pass

    # 3. Prior failures of the same case_id across other sessions.
    if db is not None:
        try:
            recent = db.list_sessions() or []
            prior: List[dict] = []
            for meta in recent[:40]:    # cap how many we open
                try:
                    snap = db.get_session(meta["session_id"]) or {}
                except Exception:
                    continue
                for tc in snap.get("test_cases") or []:
                    if (tc.get("id") == case_id
                            and tc.get("status") == "Fail"
                            and meta["session_id"] != sid):
                        prior.append({
                            "session_id": meta["session_id"],
                            "feature": meta.get("feature"),
                            "timestamp": meta.get("timestamp"),
                            "error": tc.get("error", ""),
                        })
                        if len(prior) >= 10:
                            break
                if len(prior) >= 10:
                    break
            out["prior_runs"] = prior
        except Exception:
            pass

    return out


# ---------- formatters (kept module-level so tests can hit them) ----------

def _format_action_results(results: List[dict]) -> str:
    if not results:
        return "  (no action_results recorded)"
    lines = []
    for i, r in enumerate(results, start=1):
        ok = "PASS" if r.get("success") else "FAIL"
        loc = r.get("locator_used") or ""
        attempts = r.get("attempts") or 1
        err = (r.get("error") or "")[:200]
        lines.append(
            f"  {i:>2}. [{ok}] {r.get('op','?'):<22} "
            f"dur={r.get('duration_ms','?')}ms attempts={attempts} "
            f"locator={loc} err={err}"
        )
    return "\n".join(lines)


def _format_action_plan(plan: List[dict]) -> str:
    if not plan:
        return "  (no action_plan — legacy selenium_action only)"
    lines = []
    for i, a in enumerate(plan, start=1):
        loc = a.get("locator") or {}
        loc_s = f"{loc.get('by','?')}={loc.get('value','?')}" if loc else ""
        v = a.get("value")
        v_s = f" value={str(v)[:60]}" if v not in (None, "") else ""
        url = a.get("url")
        url_s = f" url={url}" if url else ""
        lines.append(f"  {i:>2}. {a.get('op','?'):<22} {loc_s}{v_s}{url_s}")
    return "\n".join(lines)
