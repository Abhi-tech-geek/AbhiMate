"""Convert a Chrome-extension recording into an AbhiMate ``TestSession``.

The recording format is intentionally close to the existing Action Plan so
the extension can emit ops the engine already understands — no schema
translation, no field renaming.

Recording JSON shape
--------------------
::

    {
      "version": 1,
      "feature": "Login flow (recorded)",
      "url": "https://app.example.com/login",
      "recorded_at": 1716700000.0,
      "actions": [
        {"op": "goto", "url": "https://app.example.com/login"},
        {"op": "fill", "locator": {"by": "id", "value": "email",
                                    "fallbacks": [{"by": "name", "value": "email"}]},
         "value": "u@x.com"},
        {"op": "click", "locator": {"by": "text", "value": "Sign in"}}
      ]
    }

The importer
^^^^^^^^^^^^
1. Validates ``actions`` exists and is a non-empty list.
2. Caps action count (``MAX_ACTIONS``) so a runaway recording can't OOM us.
3. Builds one :class:`utils.models.TestCase` for the whole flow, tagged
   ``@recorded``. Each action becomes one Gherkin step plus an entry in
   ``action_plan`` so the existing executor can run it unchanged.
4. Wraps the case in a :class:`utils.models.TestSession` ready for
   ``memory_manager.save_session`` to persist (which enforces the quota).
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from utils.models import Action, GherkinStep, Locator, TestCase, TestSession


MAX_ACTIONS = 200
ALLOWED_OPS = {
    "goto", "back", "forward", "reload",
    "click", "fill", "press", "select", "hover",
    "wait_for", "sleep", "assert_visible", "assert_text", "assert_url",
}


class RecordingImportError(ValueError):
    """Raised when the uploaded JSON can't be parsed into a usable session."""


def _gherkin_for_action(act: Action) -> Optional[GherkinStep]:
    """Render a one-line Gherkin step describing the action.

    The extension records mechanical events (click, fill, …) so the steps
    we produce are mechanical too. Better than nothing for the human
    reader, and the action_plan is what actually runs.
    """
    op = act.op
    loc = act.locator
    target = ""
    if loc:
        target = f"{loc.by}={loc.value!r}"
    if op == "goto":
        return GherkinStep(keyword="Given", text=f"the user opens {act.url!r}")
    if op == "click":
        return GherkinStep(keyword="When",  text=f"the user clicks {target}")
    if op == "fill":
        return GherkinStep(keyword="When",
                           text=f"the user enters {act.value!r} into {target}")
    if op == "press":
        return GherkinStep(keyword="When",  text=f"the user presses {act.value!r}")
    if op == "select":
        return GherkinStep(keyword="When",
                           text=f"the user selects {act.value!r} on {target}")
    if op == "hover":
        return GherkinStep(keyword="When",  text=f"the user hovers over {target}")
    if op in ("wait_for", "assert_visible"):
        return GherkinStep(keyword="Then",  text=f"{target} is visible")
    if op == "assert_text":
        return GherkinStep(keyword="Then",
                           text=f"{target} contains {act.expected!r}")
    if op == "assert_url":
        return GherkinStep(keyword="Then",  text=f"the URL is {act.expected!r}")
    if op == "back":    return GherkinStep(keyword="When", text="the user navigates back")
    if op == "forward": return GherkinStep(keyword="When", text="the user navigates forward")
    if op == "reload":  return GherkinStep(keyword="When", text="the user reloads the page")
    return None


def _parse_action(raw: Any, index: int) -> Action:
    """Validate one recorded action and return a typed :class:`Action`."""
    if not isinstance(raw, dict):
        raise RecordingImportError(
            f"action #{index} must be an object, got {type(raw).__name__}"
        )
    op = (raw.get("op") or "").strip()
    if not op:
        raise RecordingImportError(f"action #{index} is missing 'op'")
    if op not in ALLOWED_OPS:
        raise RecordingImportError(
            f"action #{index} uses unsupported op '{op}'. "
            f"Allowed: {sorted(ALLOWED_OPS)}"
        )
    # Pydantic does the rest of the shape checking.
    try:
        return Action(**raw)
    except Exception as e:                              # noqa: BLE001
        raise RecordingImportError(f"action #{index} invalid: {e}") from e


def _feature_label(payload: dict) -> str:
    """Pick a human-readable feature label.

    Order: explicit ``feature`` field → hostname of the first ``goto`` →
    'Recorded session'.
    """
    raw = (payload.get("feature") or "").strip()
    if raw:
        return raw[:200]
    url = payload.get("url") or ""
    if not url:
        for a in payload.get("actions") or []:
            if isinstance(a, dict) and a.get("op") == "goto":
                url = a.get("url") or ""
                break
    if url:
        try:
            host = urlparse(url).hostname or ""
        except Exception:
            host = ""
        if host:
            return f"Recorded: {host}"
    return "Recorded session"


def import_recording(
    payload: dict,
    *,
    user_id: Optional[int] = None,
) -> Tuple[TestSession, dict]:
    """Convert a recording payload to a :class:`TestSession`.

    Returns ``(session, info)`` where ``info`` is a small dict the endpoint
    can echo back to the UI (counts, feature label, source URL).

    Doesn't persist — the route layer calls ``memory_manager.save_session``
    so it can map :class:`QuotaExceeded` to a 409.
    """
    if not isinstance(payload, dict):
        raise RecordingImportError("recording must be a JSON object")
    raw_actions = payload.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        raise RecordingImportError("recording must include a non-empty 'actions' list")
    if len(raw_actions) > MAX_ACTIONS:
        raise RecordingImportError(
            f"too many actions ({len(raw_actions)}). Max is {MAX_ACTIONS}."
        )

    actions: List[Action] = [_parse_action(a, i) for i, a in enumerate(raw_actions)]
    gherkin = [step for step in (_gherkin_for_action(a) for a in actions) if step is not None]
    # Plain-text step list (legacy display) — derived from the gherkin we built.
    text_steps = [f"{s.keyword} {s.text}" for s in gherkin] or [a.op for a in actions]

    feature_label = _feature_label(payload)
    source_url = payload.get("url") or next(
        (a.url for a in actions if a.op == "goto" and a.url), None,
    )

    tc = TestCase(
        id="TC001",
        type="Positive",
        scenario=feature_label,
        description=feature_label,
        steps=text_steps,
        gherkin_steps=gherkin,
        expected="The recorded user flow completes without errors.",
        tags=["@recorded"],
        action_plan=actions,
        selenium_action="",     # Phase-A path only — no legacy snippet
    )

    session = TestSession(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        feature=feature_label,
        state="GENERATED",
        timestamp=time.time(),
        test_cases=[tc],
    )
    info = {
        "feature": feature_label,
        "source_url": source_url,
        "action_count": len(actions),
        "step_count": len(gherkin),
    }
    return session, info
