"""JUnit XML serializer for an executed TestSession.

CI runners (Jenkins, GitHub Actions, GitLab, Azure DevOps) all consume the
JUnit format natively, so emitting one file per session gives us a free
dashboard wherever the suite runs.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element, SubElement, tostring

if TYPE_CHECKING:
    from utils.models import TestSession


_STATUS_TO_KIND = {
    "Fail": "failure",
    "Blocked": "error",     # sandbox/infra problem, not a test failure
    "Skipped": "skipped",
}


def session_to_junit_xml(session: "TestSession") -> str:
    """Render a TestSession as a JUnit XML string (one <testsuite>)."""
    suite_name = session.feature or session.session_id
    total = len(session.test_cases)
    failures = sum(1 for tc in session.test_cases if tc.status == "Fail")
    errors = sum(1 for tc in session.test_cases if tc.status == "Blocked")
    skipped = sum(
        1 for tc in session.test_cases
        if tc.status == "Skipped" or tc.user_skipped or tc.known_issue
    )
    total_time = sum(
        sum((r.duration_ms or 0) for r in (tc.action_results or [])) / 1000.0
        for tc in session.test_cases
    )

    suite = Element("testsuite", {
        "name": suite_name,
        "tests": str(total),
        "failures": str(failures),
        "errors": str(errors),
        "skipped": str(skipped),
        "time": f"{total_time:.3f}",
        "timestamp": str(session.timestamp),
    })

    for tc in session.test_cases:
        case_time = sum((r.duration_ms or 0) for r in (tc.action_results or [])) / 1000.0
        elem = SubElement(suite, "testcase", {
            "classname": suite_name,
            "name": f"{tc.id} {tc.description}".strip(),
            "time": f"{case_time:.3f}",
        })
        if tc.user_skipped or tc.known_issue or tc.status == "Skipped":
            reason = (
                "user_skipped" if tc.user_skipped
                else "known_issue" if tc.known_issue
                else (tc.error or "skipped")
            )
            SubElement(elem, "skipped", {"message": reason})
            continue
        kind = _STATUS_TO_KIND.get(tc.status or "")
        if kind:
            node = SubElement(elem, kind, {
                "message": (tc.error or "")[:200],
                "type": tc.status or "",
            })
            node.text = tc.error or ""

    # Pretty-ish, but the format is consumed by machines — readability is bonus.
    return '<?xml version="1.0" encoding="utf-8"?>\n' + tostring(suite, encoding="unicode")


def write_session_junit(session: "TestSession", out_dir: str = "data/junit") -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{session.session_id}.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(session_to_junit_xml(session))
    return path
