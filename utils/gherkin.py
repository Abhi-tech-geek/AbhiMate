"""Helpers for shaping raw LLM output into the Gherkin-aware TestCase model.

Two responsibilities:
1. ``normalize_raw_case`` — derive ``selenium_action``, ``steps`` (plain text),
   and rendered ``gherkin`` snippet from the LLM's ``gherkin_steps`` array, so
   the model only has to produce the structured form.
2. ``validate_case_quality`` — soft warnings about missing waits, asserts on
   Then-steps, or missing semantic locators. Returns a list of warning strings;
   never raises.
"""

from typing import List, Dict, Any


_KEYWORDS = ("Given", "When", "Then", "And", "But")


def normalize_raw_case(rc: Dict[str, Any], feature_label: str = "") -> Dict[str, Any]:
    """Mutate-free: returns a new dict ready for ``TestCase(**)``."""
    out = dict(rc)

    gherkin_steps = out.get("gherkin_steps") or []

    # Derive plain-text steps (legacy field used by the existing UI).
    derived_steps: List[str] = []
    code_chunks: List[str] = []
    for step in gherkin_steps:
        kw = step.get("keyword", "And")
        text = step.get("text", "").strip()
        code = (step.get("code") or "").strip()
        derived_steps.append(f"{kw} {text}".strip())
        if code:
            code_chunks.append(code)

    # Backfill required + display fields.
    if "steps" not in out or not out["steps"]:
        out["steps"] = derived_steps or ["(no steps)"]

    # Phase A: action_plan is the preferred execution payload. If only legacy
    # selenium_action snippets are present, leave them; the executor will pick
    # the path automatically.
    has_action_plan = bool(out.get("action_plan"))

    if "selenium_action" not in out or not out["selenium_action"]:
        # Empty string is fine when action_plan is present — model schema allows it.
        out["selenium_action"] = "\n".join(code_chunks) if code_chunks else ""
        if not has_action_plan and not out["selenium_action"]:
            out["selenium_action"] = "pass"  # safety: keep legacy path valid

    if "feature" not in out and feature_label:
        out["feature"] = feature_label

    if "scenario" not in out:
        out["scenario"] = out.get("description", "")

    if "description" not in out or not out["description"]:
        out["description"] = out.get("scenario") or "(no description)"

    # Render a clean .feature snippet for the UI.
    out["gherkin"] = render_gherkin(
        feature=out.get("feature") or feature_label or "Feature",
        scenario=out.get("scenario") or out["description"],
        tags=out.get("tags") or [],
        steps=gherkin_steps,
        examples=out.get("examples") or [],
    )

    # Normalize tags to a list of strings (some LLMs return space-joined).
    raw_tags = out.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = raw_tags.split()
    out["tags"] = [t.strip() for t in raw_tags if t.strip()]

    return out


def render_gherkin(feature: str, scenario: str, tags, steps, examples) -> str:
    """Best-effort .feature text render for display only."""
    lines: List[str] = []
    if feature:
        lines.append(f"Feature: {feature}")
        lines.append("")
    if tags:
        lines.append("  " + " ".join(tags))
    lines.append(f"  Scenario: {scenario}")
    for step in steps:
        kw = step.get("keyword", "And")
        text = step.get("text", "")
        lines.append(f"    {kw} {text}")
    if examples:
        lines.append("")
        lines.append("    Examples:")
        keys = list(examples[0].keys()) if examples else []
        if keys:
            lines.append("      | " + " | ".join(keys) + " |")
            for row in examples:
                lines.append("      | " + " | ".join(str(row.get(k, "")) for k in keys) + " |")
    return "\n".join(lines)


def validate_case_quality(tc) -> List[str]:
    """Soft heuristic check. Returns list of warning strings (no exceptions)."""
    warnings: List[str] = []

    code = tc.selenium_action or ""

    # Encourage explicit waits.
    if "WebDriverWait" not in code and "time.sleep" not in code:
        warnings.append("no explicit wait detected")

    # Encourage assertion on Then-steps.
    has_then = any(s.keyword == "Then" for s in (tc.gherkin_steps or []))
    if has_then and "assert" not in code:
        warnings.append("no assert statement found despite Then-step")

    # Locator hint — penalize bare xpath when nothing else is used.
    if "By.XPATH" in code and "By.ID" not in code and "By.NAME" not in code and "By.CSS_SELECTOR" not in code:
        warnings.append("only XPATH locators used — consider semantic ID/NAME")

    return warnings


def expand_examples(tc) -> List:
    """Scenario-Outline expansion: returns a list of TestCase instances.

    For every row in ``tc.examples``, substitute ``<col>`` placeholders inside
    each step's text and code. If no examples are present, returns ``[tc]``.
    """
    from utils.models import TestCase, GherkinStep

    if not tc.examples:
        return [tc]

    expanded: List = []
    for idx, row in enumerate(tc.examples, start=1):
        new_steps: List[GherkinStep] = []
        for step in tc.gherkin_steps:
            substituted_text = _substitute(step.text, row)
            substituted_code = _substitute(step.code or "", row) if step.code else step.code
            new_steps.append(
                GherkinStep(keyword=step.keyword, text=substituted_text, code=substituted_code)
            )

        derived_steps = [f"{s.keyword} {s.text}" for s in new_steps]
        selenium_action = "\n".join(s.code for s in new_steps if s.code) or "pass"

        expanded.append(
            TestCase(
                id=f"{tc.id}_{idx:02d}",
                type=tc.type,
                tags=tc.tags,
                feature=tc.feature,
                scenario=f"{tc.scenario} [example {idx}]" if tc.scenario else None,
                description=f"{tc.description} | " + ", ".join(f"{k}={v}" for k, v in row.items()),
                gherkin_steps=new_steps,
                steps=derived_steps,
                examples=[],
                gherkin=render_gherkin(
                    feature=tc.feature or "",
                    scenario=f"{tc.scenario or tc.description} [example {idx}]",
                    tags=tc.tags,
                    steps=[s.model_dump() for s in new_steps],
                    examples=[],
                ),
                selenium_action=selenium_action,
                expected=tc.expected,
            )
        )
    return expanded


def _substitute(text: str, row: Dict[str, str]) -> str:
    out = text
    for k, v in row.items():
        out = out.replace(f"<{k}>", str(v))
    return out
