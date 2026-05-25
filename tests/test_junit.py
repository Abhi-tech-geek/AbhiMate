"""JUnit serializer tests."""

import xml.etree.ElementTree as ET

from utils.junit import session_to_junit_xml
from utils.models import TestCase, TestSession, ActionResult


def make_session():
    return TestSession(
        session_id="abc123",
        feature="Login feature",
        state="EXECUTED",
        timestamp=1700000000.0,
        test_cases=[
            TestCase(
                id="TC001", type="Positive", description="happy path",
                steps=["s"], selenium_action="pass", expected="ok",
                status="Pass",
                action_results=[ActionResult(op="goto", success=True, duration_ms=120)],
            ),
            TestCase(
                id="TC002", type="Negative", description="bad creds",
                steps=["s"], selenium_action="pass", expected="error",
                status="Fail", error="AssertionError: bad",
                action_results=[ActionResult(op="click", success=False, duration_ms=80,
                                              error="AssertionError: bad")],
            ),
            TestCase(
                id="TC003", type="Edge", description="skipped by user",
                steps=["s"], selenium_action="pass", expected="ok",
                user_skipped=True,
            ),
            TestCase(
                id="TC004", type="Security", description="blocked by sandbox",
                steps=["s"], selenium_action="pass", expected="ok",
                status="Blocked", error="SandboxViolation: import os",
            ),
        ],
    )


def test_junit_xml_parses():
    xml = session_to_junit_xml(make_session())
    root = ET.fromstring(xml)
    assert root.tag == "testsuite"
    assert root.attrib["tests"] == "4"
    assert root.attrib["failures"] == "1"
    assert root.attrib["errors"] == "1"
    assert root.attrib["skipped"] == "1"


def test_junit_includes_failure_message():
    xml = session_to_junit_xml(make_session())
    assert "AssertionError: bad" in xml
    assert "SandboxViolation" in xml


def test_junit_marks_user_skipped():
    xml = session_to_junit_xml(make_session())
    root = ET.fromstring(xml)
    tc3 = next(tc for tc in root.findall("testcase") if "TC003" in tc.attrib["name"])
    skipped = tc3.find("skipped")
    assert skipped is not None
    assert skipped.attrib["message"] == "user_skipped"
