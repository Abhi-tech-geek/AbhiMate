"""Slack incoming-webhook poster for scheduled runs (Feature #7).

Exposes one public function — :func:`post_run_result` — that takes an
ExecutionMetrics snapshot + the list of run TestCases and ships a Block
Kit payload with:

  * A coloured header ("All 12 tests passed", "3 of 12 failed", etc.)
  * Per-failure bullet list (id + status + first line of error)
  * A link back to the AbhiMate session

Why Block Kit (not just text)?
------------------------------
Slack truncates plain ``text`` at ~3000 chars and gives no visual
priority. Blocks let us pin the headline at the top with a colour
emoji, show details in a code-fenced section, and still degrade
gracefully (``text`` is included as the notification preview).

The poster is intentionally I/O-only — no DB writes, no executor
imports — so it stays trivially testable with a mock HTTP layer.
"""

from __future__ import annotations

import json as _json
from typing import Iterable, List, Optional

import requests


SLACK_WEBHOOK_PREFIX = "https://hooks.slack.com/"
_DEFAULT_TIMEOUT_SEC = 8.0


class SlackError(RuntimeError):
    """Raised on transport / 4xx-5xx errors from Slack."""


def validate_webhook_url(url: str) -> str:
    """Return the normalised URL or raise :class:`SlackError`."""
    if not isinstance(url, str) or not url.strip():
        raise SlackError("Slack webhook URL is required")
    url = url.strip()
    if not url.startswith(SLACK_WEBHOOK_PREFIX):
        raise SlackError(
            "Slack webhook URL must start with https://hooks.slack.com/"
        )
    return url


# ---------------------------------------------------------------------
# Block builders
# ---------------------------------------------------------------------

def _status_emoji(failed: int, total: int) -> str:
    if total == 0:
        return ":zzz:"
    if failed == 0:
        return ":large_green_circle:"
    if failed < total / 2:
        return ":large_yellow_circle:"
    return ":red_circle:"


def _format_failure_lines(cases: Iterable, max_lines: int = 8) -> List[str]:
    """Pull the first ``max_lines`` failures into compact one-line summaries."""
    lines: List[str] = []
    for tc in cases:
        status = getattr(tc, "status", None) or (tc.get("status") if isinstance(tc, dict) else None)
        if status != "Fail":
            continue
        tc_id = getattr(tc, "id", None) or (tc.get("id") if isinstance(tc, dict) else "?")
        err = getattr(tc, "error", None) or (tc.get("error") if isinstance(tc, dict) else "") or ""
        first_line = err.splitlines()[0] if err else "(no error message)"
        # Slack code fences look weird with backticks inside, so escape.
        first_line = first_line.replace("`", "ʼ")[:200]
        lines.append(f"• *{tc_id}* — {first_line}")
        if len(lines) >= max_lines:
            break
    return lines


def build_run_payload(
    *,
    session_feature: str,
    session_id: str,
    metrics: dict,
    test_cases: Iterable,
    session_url: Optional[str] = None,
    schedule_expr: Optional[str] = None,
    mention_on_fail: Optional[str] = None,
    error: Optional[str] = None,
) -> dict:
    """Render the Block Kit JSON for one run result.

    ``metrics`` is a plain dict {total, passed, failed, skipped}. Passing
    a Pydantic model also works — call ``.model_dump()`` first.
    """
    total = int(metrics.get("total", 0) or 0)
    passed = int(metrics.get("passed", 0) or 0)
    failed = int(metrics.get("failed", 0) or 0)
    skipped = int(metrics.get("skipped", 0) or 0)

    headline = (
        f"{_status_emoji(failed, total)} *AbhiMate* — "
        f"{passed}/{total} passed"
        + (f", {failed} failed" if failed else "")
        + (f", {skipped} skipped" if skipped else "")
    )

    blocks: List[dict] = [
        {"type": "header", "text": {"type": "plain_text",
                                    "text": "AbhiMate scheduled run"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": headline}},
        {"type": "context", "elements": [
            {"type": "mrkdwn",
             "text": (f"*Feature:* {session_feature}"
                      + (f"   ·   *Schedule:* `{schedule_expr}`" if schedule_expr else "")
                      + f"   ·   *Session:* `{session_id[:8]}`")},
        ]},
    ]

    if error:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
                       "text": f":warning: Run aborted: `{error[:300]}`"}})

    failure_lines = _format_failure_lines(test_cases) if failed else []
    if failure_lines:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
                       "text": "*Failures:*\n" + "\n".join(failure_lines)}})

    if failed and mention_on_fail:
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
                       "text": mention_on_fail}})

    if session_url:
        blocks.append({"type": "actions", "elements": [{
            "type": "button",
            "text": {"type": "plain_text", "text": "Open in AbhiMate"},
            "url": session_url,
        }]})

    # ``text`` is what Slack shows in notifications + fallback clients.
    fallback_text = headline.replace("*", "")
    return {"text": fallback_text, "blocks": blocks}


# ---------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------

def post_payload(webhook_url: str, payload: dict, *,
                 session: Optional[requests.Session] = None,
                 timeout: float = _DEFAULT_TIMEOUT_SEC) -> None:
    """POST the Block Kit payload. Raises :class:`SlackError` on any failure."""
    validate_webhook_url(webhook_url)
    sess = session or requests
    try:
        resp = sess.post(webhook_url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise SlackError(f"Slack request failed: {e}") from e
    if resp.status_code >= 400:
        raise SlackError(
            f"Slack returned {resp.status_code}: {resp.text[:200] or '(empty)'}"
        )


def post_run_result(
    webhook_url: str,
    *,
    session_feature: str,
    session_id: str,
    metrics: dict,
    test_cases: Iterable,
    session_url: Optional[str] = None,
    schedule_expr: Optional[str] = None,
    mention_on_fail: Optional[str] = None,
    error: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> dict:
    """Build the payload + send. Returns the payload that was sent (handy
    for logging + tests)."""
    payload = build_run_payload(
        session_feature=session_feature,
        session_id=session_id,
        metrics=metrics,
        test_cases=test_cases,
        session_url=session_url,
        schedule_expr=schedule_expr,
        mention_on_fail=mention_on_fail,
        error=error,
    )
    post_payload(webhook_url, payload, session=session)
    return payload


def post_test_message(webhook_url: str, *,
                      session: Optional[requests.Session] = None) -> None:
    """One-line "AbhiMate is connected" hello — used by the Settings 'Send test' button."""
    post_payload(
        webhook_url,
        {
            "text": "AbhiMate is connected. Scheduled runs will post here.",
            "blocks": [{
                "type": "section",
                "text": {"type": "mrkdwn",
                         "text": ":wave: *AbhiMate* is connected. "
                                 "Scheduled runs will post their results here."},
            }],
        },
        session=session,
    )
